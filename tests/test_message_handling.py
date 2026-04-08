from hyde.message_handling import HydeInbox, handle_lyse_request


def test_lyse_compatibility_payloads():
    inbox = HydeInbox()
    received = []

    assert handle_lyse_request("hello", inbox, received.append) == "hello"
    assert (
        handle_lyse_request({"filepath": "/tmp/test.h5"}, inbox, received.append)
        == "added successfully"
    )
    assert received == ["/tmp/test.h5"]
    dataframe = handle_lyse_request("get dataframe", inbox, received.append)
    assert list(dataframe["filepath"]) == ["/tmp/test.h5"]

