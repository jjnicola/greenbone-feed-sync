# Copyright (C) 2023 Greenbone Networks GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import errno
import unittest
from io import StringIO
from unittest.mock import MagicMock, call, patch

from pontos.testing import temp_directory
from rich.console import Console

from greenbone.feed.sync.errors import FileLockingError
from greenbone.feed.sync.helper import (
    Spinner,
    change_user_and_group,
    flock_wait,
    is_root,
)


class FlockTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_locking(self):
        with temp_directory() as temp_dir:
            lock_file = temp_dir / "file.lock"
            self.assertFalse(lock_file.exists())

            async with flock_wait(lock_file):
                self.assertTrue(lock_file.exists())

                with self.assertRaises(FileLockingError):
                    async with flock_wait(lock_file, wait_interval=None):
                        pass

    async def test_can_not_create_parent_dirs(self):
        with temp_directory() as temp_dir:
            lock_file = temp_dir / "foo" / "file.lock"
            temp_dir.chmod(0)

            with self.assertRaisesRegex(
                FileLockingError, "Could not create parent directories for "
            ):
                async with flock_wait(lock_file):
                    pass

    async def test_console_output(self):
        with temp_directory() as temp_dir:
            lock_file = temp_dir / "file.lock"
            console = MagicMock(spec=Console)

            async with flock_wait(lock_file, console=console):
                pass

            console.print.assert_has_calls(
                [
                    call(f"Trying to acquire lock on {lock_file.absolute()}"),
                    call(f"Acquired lock on {lock_file.absolute()}"),
                    call(f"Releasing lock on {lock_file.absolute()}"),
                ]
            )

    @patch("greenbone.feed.sync.helper.fcntl.flock", autospec=True)
    async def test_retry(self, flock_mock: MagicMock):
        e = OSError()
        e.errno = errno.EACCES

        flock_mock.side_effect = [e, None, None]

        with temp_directory() as temp_dir:
            lock_file = temp_dir / "file.lock"
            console = MagicMock(spec=Console)

            async with flock_wait(
                lock_file, console=console, wait_interval=0.5
            ):
                pass

            console.print.assert_has_calls(
                [
                    call(f"Trying to acquire lock on {lock_file.absolute()}"),
                    call(
                        f"{lock_file.absolute()} is locked by another process."
                        " Waiting 0.5 seconds before next try."
                    ),
                    call(f"Trying to acquire lock on {lock_file.absolute()}"),
                    call(f"Acquired lock on {lock_file.absolute()}"),
                    call(f"Releasing lock on {lock_file.absolute()}"),
                ]
            )

    @patch("greenbone.feed.sync.helper.fcntl.flock", autospec=True)
    async def test_lock_failure(self, flock_mock: MagicMock):
        e = OSError()
        e.errno = errno.EACCES

        flock_mock.side_effect = e

        with temp_directory() as temp_dir:
            lock_file = temp_dir / "file.lock"

            with self.assertRaisesRegex(
                FileLockingError,
                f"{lock_file.absolute()} is locked. Another process related "
                "to the feed update may already running.",
            ):
                async with flock_wait(
                    lock_file,
                    wait_interval=None,
                ):
                    pass

    @patch("greenbone.feed.sync.helper.fcntl.flock", autospec=True)
    async def test_lock_other_failure(self, flock_mock: MagicMock):
        e = OSError("Other OSError")
        flock_mock.side_effect = e

        with temp_directory() as temp_dir:
            lock_file = temp_dir / "file.lock"

            with self.assertRaisesRegex(OSError, "Other OSError"):
                async with flock_wait(
                    lock_file,
                    wait_interval=None,
                ):
                    pass

    @patch("greenbone.feed.sync.helper.fcntl.flock", autospec=True)
    async def test_unlock_oserror(self, flock_mock: MagicMock):
        flock_mock.side_effect = [None, OSError]

        with temp_directory() as temp_dir:
            lock_file = temp_dir / "file.lock"
            async with flock_wait(
                lock_file,
            ):
                pass


class SpinnerTestCase(unittest.TestCase):
    @patch("greenbone.feed.sync.helper.Live", autospec=True)
    def test_context_manager(self, live_mock: MagicMock):
        console = MagicMock(spec=Console)
        with Spinner(console, "Some Text"):
            pass

        live_mock_instance = live_mock.return_value
        live_mock_instance.start.assert_called_once_with()
        live_mock_instance.stop.assert_called_once_with()

    def test_render(self):
        out = StringIO()
        console = Console(file=out)
        with Spinner(console, "Some Text"):
            pass

        self.assertEqual("⠋ Some Text", out.getvalue())


class IsRootTestCase(unittest.TestCase):
    @patch("greenbone.feed.sync.helper.os.geteuid", autospec=True)
    def test_not_root(self, geteuid_mock: MagicMock):
        geteuid_mock.return_value = 123

        self.assertFalse(is_root())

    @patch("greenbone.feed.sync.helper.os.geteuid", autospec=True)
    def test_root(self, geteuid_mock: MagicMock):
        geteuid_mock.return_value = 0

        self.assertTrue(is_root())


class ChangeUserAndGroupTestCase(unittest.TestCase):
    @patch("greenbone.feed.sync.helper.os", autospec=True)
    def test_change(self, os_mock: MagicMock):
        # root user should exist on all systems
        change_user_and_group("root", "root")

        os_mock.seteuid.assert_called_once_with(0)
        os_mock.setegid.assert_called_once_with(0)
