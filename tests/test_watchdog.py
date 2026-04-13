import os
import sys
import time
import unittest
import subprocess
import tempfile
from pathlib import Path

from labscript_utils.ls_zprocess import ProcessTree
from jupyter_client import BlockingKernelClient

import hyde
from hyde.paths import CONNECTION_FILE

class TestWatchdogArchitecture(unittest.TestCase):
    def test_kernel_launcher_runs_spyder_in_process(self):
        launcher_path = Path(os.path.dirname(hyde.__file__)) / "execution" / "kernel_launcher.py"
        source = launcher_path.read_text()

        self.assertIn("from spyder_kernels.console.start import main as start_spyder_kernel", source)
        self.assertIn("start_spyder_kernel()", source)
        self.assertNotIn("subprocess.Popen", source)

    def wait_for_code_ok(self, client, code, timeout=5):
        deadline = time.time() + timeout
        last_reply = None
        while time.time() < deadline:
            msg_id = client.execute(code)
            reply = client.get_shell_msg(timeout=5)
            if reply['parent_header'].get('msg_id') != msg_id:
                continue
            last_reply = reply
            if reply['content']['status'] == 'ok':
                return
            time.sleep(0.1)
        self.fail(f"Code did not succeed within {timeout} seconds: {code!r}\nLast reply: {last_reply}")

    def drain_iopub(self, client, timeout=0.2):
        while True:
            try:
                client.get_iopub_msg(timeout=timeout)
            except Exception:
                return

    def collect_iopub_until_idle(self, client, timeout=5):
        deadline = time.time() + timeout
        messages = []
        saw_busy = False
        while time.time() < deadline:
            try:
                msg = client.get_iopub_msg(timeout=0.5)
            except Exception:
                continue
            messages.append(msg)
            if msg['msg_type'] != 'status':
                continue
            state = msg['content'].get('execution_state')
            if state == 'busy':
                saw_busy = True
            elif saw_busy and state == 'idle':
                return messages
        self.fail(f"Did not observe execution idle state within {timeout} seconds. Messages: {messages!r}")

    def test_kernel_lifecycle_and_execution(self):
        """
        Tests the full Phase II / III Architecture:
        1. Spins up the execution watchdog through ProcessTree.
        2. Waits for KERNEL_READY synchronous alert from the background.
        3. Connects an isolated BlockingKernelClient directly to the kernel-hyde.json port schema.
        4. Injects a raw string payload to execute.
        5. Gracefully triggers ProcessTree tear-down and verifies clean Watchdog exit.
        """
        # 1. Setup ProcessTree mimic (acts as HydeApp)
        process_tree = ProcessTree.instance()
        process_tree.zlock_client.set_process_name('hyde-test')
        
        controller_path = os.path.abspath(
            os.path.join(os.path.dirname(hyde.__file__), 'execution', 'execution_controller.py')
        )
        
        # 2. Spawning Watchdog Subprocess
        print(f"\n[Test] Spawning Watchdog: {controller_path}")
        to_worker, from_worker, worker = process_tree.subprocess(
            controller_path,
            args=[CONNECTION_FILE],
        )
        
        # 3. Wait for KERNEL_READY
        try:
            task, data = from_worker.get(timeout=15)
            self.assertEqual(task, 'KERNEL_READY')
            print("[Test] KERNEL_READY successfully intercepted.")
        except Exception as e:
            self.fail(f"Did not receive KERNEL_READY from Watchdog: {e}")
        
        # 4. Verify connection file dropped perfectly into the target directory
        self.assertEqual(data, CONNECTION_FILE)
        self.assertTrue(os.path.exists(CONNECTION_FILE))
        print(f"[Test] IPC File {CONNECTION_FILE} validated.")
        
        # 5. Connect ZMQ Client securely explicitly bypassing the PyQt event loop
        client = BlockingKernelClient(connection_file=CONNECTION_FILE)
        client.load_connection_file()
        client.start_channels()
        
        try:
            client.wait_for_ready(timeout=5)
            
            # Send execution string
            print("[Test] Injecting 1+1 Python string into Spyder execution namespace...")
            msg_id = client.execute("1 + 1")
            
            # Get execution reply
            reply = client.get_shell_msg(timeout=5)
            
            # Verify status is exactly "ok"
            self.assertEqual(reply['content']['status'], 'ok')
            print("[Test] ZMQ Socket responded OK!")
            
        finally:
            client.stop_channels()
            
        # 6. Graceful Teardown
        print("[Test] Sending QUIT queue dispatch to Watchdog.")
        to_worker.put(['QUIT', None])
        
        # 7. Verify Watchdog terminated natively (timeout heavily since IPython teardown takes a sec)
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.fail("Watchdog process failed to exit within 10 seconds of receiving QUIT.")
            
        self.assertIsNotNone(worker.poll())
        print("[Test] Watchdog cleanly terminated.")

    def test_watch_project_reloads_package_init(self):
        process_tree = ProcessTree.instance()
        process_tree.zlock_client.set_process_name('hyde-test')

        controller_path = os.path.abspath(
            os.path.join(os.path.dirname(hyde.__file__), 'execution', 'execution_controller.py')
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, 'reload_test.hy')
            procedures_dir = os.path.join(project_dir, 'procedures')
            os.makedirs(procedures_dir)
            procedures_init = os.path.join(procedures_dir, '__init__.py')
            with open(procedures_init, 'w') as f:
                f.write("VALUE = 1\n")

            to_worker, from_worker, worker = process_tree.subprocess(
                controller_path,
                args=[CONNECTION_FILE],
            )

            to_worker.put([
                'WATCH_PROJECT',
                {
                    'project_dir': project_dir,
                    'procedures_dir': procedures_dir,
                    'procedures_init': procedures_init,
                },
            ])

            try:
                task, data = from_worker.get(timeout=15)
                self.assertEqual(task, 'KERNEL_READY')

                client = BlockingKernelClient(connection_file=CONNECTION_FILE)
                client.load_connection_file()
                client.start_channels()

                try:
                    client.wait_for_ready(timeout=5)
                    self.wait_for_code_ok(client, "assert VALUE == 1")
                    self.wait_for_code_ok(client, "import procedures; assert procedures.VALUE == VALUE")

                    with open(procedures_init, 'w') as f:
                        f.write("VALUE = 2\n")

                    time.sleep(1.5)
                    self.wait_for_code_ok(client, "assert VALUE == 2", timeout=10)
                    self.wait_for_code_ok(client, "import procedures; assert procedures.VALUE == VALUE", timeout=10)
                finally:
                    client.stop_channels()
            finally:
                to_worker.put(['QUIT', None])
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.fail("Watchdog process failed to exit within 10 seconds of receiving QUIT.")

    def test_watch_project_executes_package_init_silently(self):
        process_tree = ProcessTree.instance()
        process_tree.zlock_client.set_process_name('hyde-test')

        controller_path = os.path.abspath(
            os.path.join(os.path.dirname(hyde.__file__), 'execution', 'execution_controller.py')
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, 'silent_test.hy')
            procedures_dir = os.path.join(project_dir, 'procedures')
            os.makedirs(procedures_dir)
            procedures_init = os.path.join(procedures_dir, '__init__.py')
            with open(procedures_init, 'w') as f:
                f.write('print("masked output")\nVALUE = 1\n')

            to_worker, from_worker, worker = process_tree.subprocess(
                controller_path,
                args=[CONNECTION_FILE],
            )

            to_worker.put([
                'WATCH_PROJECT',
                {
                    'project_dir': project_dir,
                    'procedures_dir': procedures_dir,
                    'procedures_init': procedures_init,
                },
            ])

            try:
                task, data = from_worker.get(timeout=15)
                self.assertEqual(task, 'KERNEL_READY')

                client = BlockingKernelClient(connection_file=CONNECTION_FILE)
                client.load_connection_file()
                client.start_channels()

                try:
                    client.wait_for_ready(timeout=5)
                    self.drain_iopub(client)

                    to_worker.put([
                        'WATCH_PROJECT',
                        {
                            'project_dir': project_dir,
                            'procedures_dir': procedures_dir,
                            'procedures_init': procedures_init,
                        },
                    ])

                    messages = self.collect_iopub_until_idle(client, timeout=10)

                    self.assertTrue(
                        any(
                            msg['msg_type'] == 'stream'
                            and 'masked output' in msg['content'].get('text', '')
                            for msg in messages
                        ),
                        msg=f"Expected stream output from silent package-init execution. Messages: {messages!r}",
                    )
                    self.assertFalse(
                        any(msg['msg_type'] == 'execute_input' for msg in messages),
                        msg=f"Silent package-init execution should not emit execute_input. Messages: {messages!r}",
                    )

                    msg_id = client.execute("1 + 1")
                    while True:
                        reply = client.get_shell_msg(timeout=5)
                        if reply['parent_header'].get('msg_id') == msg_id:
                            break
                    self.assertEqual(reply['content']['status'], 'ok')
                    self.assertEqual(reply['content']['execution_count'], 1)
                finally:
                    client.stop_channels()
            finally:
                to_worker.put(['QUIT', None])
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.fail("Watchdog process failed to exit within 10 seconds of receiving QUIT.")

    def test_hyde_table_request_reaches_watchdog(self):
        process_tree = ProcessTree.instance()
        process_tree.zlock_client.set_process_name('hyde-test')

        controller_path = os.path.abspath(
            os.path.join(os.path.dirname(hyde.__file__), 'execution', 'execution_controller.py')
        )

        to_worker, from_worker, worker = process_tree.subprocess(
            controller_path,
            args=[CONNECTION_FILE],
        )

        try:
            task, data = from_worker.get(timeout=15)
            self.assertEqual(task, 'KERNEL_READY')

            client = BlockingKernelClient(connection_file=CONNECTION_FILE)
            client.load_connection_file()
            client.start_channels()

            try:
                client.wait_for_ready(timeout=5)
                msg_id = client.execute(
                    "import numpy as np, hyde\n"
                    "c = np.arange(4)\n"
                    "hyde.table(c)\n"
                )
                while True:
                    reply = client.get_shell_msg(timeout=5)
                    if reply['parent_header'].get('msg_id') == msg_id:
                        break
                self.assertEqual(reply['content']['status'], 'ok')

                task, payload = from_worker.get(timeout=10)
                self.assertEqual(task, 'OPEN_TABLE')
                self.assertEqual(payload['names'], ['c'])
                self.assertIsNone(payload['target'])
            finally:
                client.stop_channels()
        finally:
            to_worker.put(['QUIT', None])
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.fail("Watchdog process failed to exit within 10 seconds of receiving QUIT.")

    def test_watch_project_starts_with_only_package_init(self):
        process_tree = ProcessTree.instance()
        process_tree.zlock_client.set_process_name('hyde-test')

        controller_path = os.path.abspath(
            os.path.join(os.path.dirname(hyde.__file__), 'execution', 'execution_controller.py')
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, 'package_init_only.hy')
            procedures_dir = os.path.join(project_dir, 'procedures')
            os.makedirs(procedures_dir)
            procedures_init = os.path.join(procedures_dir, '__init__.py')
            with open(procedures_init, 'w') as f:
                f.write('VALUE = 1\n')

            self.assertFalse(os.path.exists(os.path.join(procedures_dir, 'master.py')))

            to_worker, from_worker, worker = process_tree.subprocess(
                controller_path,
                args=[CONNECTION_FILE],
            )

            to_worker.put([
                'WATCH_PROJECT',
                {
                    'project_dir': project_dir,
                    'procedures_dir': procedures_dir,
                    'procedures_init': procedures_init,
                },
            ])

            try:
                task, data = from_worker.get(timeout=15)
                self.assertEqual(task, 'KERNEL_READY')

                client = BlockingKernelClient(connection_file=CONNECTION_FILE)
                client.load_connection_file()
                client.start_channels()

                try:
                    client.wait_for_ready(timeout=5)
                    self.wait_for_code_ok(client, "assert VALUE == 1", timeout=10)
                    self.wait_for_code_ok(client, "import procedures; assert procedures.VALUE == VALUE", timeout=10)
                finally:
                    client.stop_channels()
            finally:
                to_worker.put(['QUIT', None])
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.fail("Watchdog process failed to exit within 10 seconds of receiving QUIT.")

if __name__ == '__main__':
    unittest.main()
