import os
import sys
import time
import unittest
import subprocess

from labscript_utils.ls_zprocess import ProcessTree
from jupyter_client import BlockingKernelClient

import hyde

class TestWatchdogArchitecture(unittest.TestCase):
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
        to_worker, from_worker, worker = process_tree.subprocess(controller_path)
        
        # 3. Wait for KERNEL_READY
        try:
            task, data = from_worker.get(timeout=15)
            self.assertEqual(task, 'KERNEL_READY')
            print("[Test] KERNEL_READY successfully intercepted.")
        except Exception as e:
            self.fail(f"Did not receive KERNEL_READY from Watchdog: {e}")
        
        # 4. Verify connection file dropped perfectly into the target directory
        connection_file = os.path.join(os.path.dirname(hyde.__file__), 'kernel-hyde.json')
        self.assertTrue(os.path.exists(connection_file))
        print(f"[Test] IPC File {connection_file} validated.")
        
        # 5. Connect ZMQ Client securely explicitly bypassing the PyQt event loop
        client = BlockingKernelClient(connection_file=connection_file)
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

if __name__ == '__main__':
    unittest.main()
