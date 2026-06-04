from __future__ import annotations

import contextlib
import socket
from typing import Iterator
from unittest.mock import patch


@contextlib.contextmanager
def assert_no_network() -> Iterator[None]:
    """Fail the block if code tries to create a network socket."""

    def blocked_socket(*args, **kwargs):
        raise AssertionError("network access is forbidden in offline replay mode")

    with patch.object(socket, "socket", side_effect=blocked_socket):
        yield
