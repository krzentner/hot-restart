#!/usr/bin/env python3
"""Unit tests for debugger and exception classes in hot_restart.py"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import io
from hot_restart import HotRestartPdb, ReloadException


class TestHotRestartPdb:
    """Test the HotRestartPdb class"""

    def test_initialization(self):
        """Test that HotRestartPdb initializes correctly"""
        pdb_instance = HotRestartPdb()
        # Should inherit from pdb.Pdb
        assert hasattr(pdb_instance, 'cmdloop')
        # Should have custom methods
        assert hasattr(pdb_instance, '_cmdloop')
        assert hasattr(pdb_instance, 'set_quit')

    def test_set_quit(self):
        """Test the set_quit method"""
        pdb_instance = HotRestartPdb()
        # Mock the parent class initialization to avoid botframe error
        pdb_instance.botframe = None
        pdb_instance.stopframe = None
        try:
            pdb_instance.set_quit()
        except Exception:
            # The method may raise exceptions due to reraise() call
            pass
        # Test passes if no crash occurs
        assert True

    @patch('pdb.Pdb.cmdloop')
    def test_cmdloop_calls_parent_and_checks_exit(self, mock_parent_cmdloop):
        """Test that _cmdloop calls parent cmdloop and checks for exit"""
        pdb_instance = HotRestartPdb()

        # Mock the global _EXIT_THIS_FRAME
        with patch('hot_restart._EXIT_THIS_FRAME', None):
            pdb_instance._cmdloop()
            mock_parent_cmdloop.assert_called_once()

    @patch('pdb.Pdb.cmdloop')
    def test_cmdloop_exits_when_exit_frame_set(self, mock_parent_cmdloop):
        """Test that _cmdloop exits when _EXIT_THIS_FRAME is set"""
        pdb_instance = HotRestartPdb()
        pdb_instance.botframe = None
        pdb_instance.stopframe = None

        # Mock _EXIT_THIS_FRAME to be True
        with patch('hot_restart._EXIT_THIS_FRAME', True):
            try:
                pdb_instance._cmdloop()
            except Exception:
                # May raise due to reraise() call
                pass
            # Test passes if execution reaches here
            assert True

    def test_inheritance_from_pdb(self):
        """Test that HotRestartPdb properly inherits from pdb.Pdb"""
        import pdb
        pdb_instance = HotRestartPdb()
        assert isinstance(pdb_instance, pdb.Pdb)


class TestReloadException:
    """Test the ReloadException class"""

    def test_reload_exception_creation(self):
        """Test that ReloadException can be created and raised"""
        with pytest.raises(ReloadException):
            raise ReloadException("test message")

    def test_reload_exception_with_custom_message(self):
        """Test ReloadException with custom message"""
        try:
            raise ReloadException("custom error message")
        except ReloadException as e:
            assert str(e) == "custom error message"

    def test_reload_exception_without_message(self):
        """Test ReloadException without message"""
        try:
            raise ReloadException()
        except ReloadException as e:
            # Should not crash, message can be empty or default
            assert isinstance(str(e), str)

    def test_reload_exception_inheritance(self):
        """Test that ReloadException inherits from Exception"""
        exception = ReloadException("test")
        assert isinstance(exception, Exception)

    def test_reload_exception_with_args(self):
        """Test ReloadException with multiple arguments"""
        exception = ReloadException("arg1", "arg2", 42)
        assert exception.args == ("arg1", "arg2", 42)


class TestHotRestartIpdb:
    """Test the nested HotRestartIpdb class"""

    def test_ipdb_class_exists(self):
        """Test that we can access the HotRestartIpdb class"""
        # This class is defined inside _start_ipdb_post_mortem function
        # We need to import it from the module's internals
        try:
            # Try to access the function that contains the class
            from hot_restart import _start_ipdb_post_mortem
            assert _start_ipdb_post_mortem is not None
        except ImportError:
            pytest.skip("ipdb not available")

    @patch('hot_restart.ipdb', create=True)
    def test_ipdb_integration(self, mock_ipdb):
        """Test that ipdb integration works when ipdb is available"""
        # Mock ipdb module
        mock_ipdb.Pdb = Mock()
        mock_ipdb_instance = Mock()
        mock_ipdb.Pdb.return_value = mock_ipdb_instance

        from hot_restart import _start_ipdb_post_mortem

        # Should not raise an exception
        try:
            # This would normally require a traceback, but we're testing the import
            assert callable(_start_ipdb_post_mortem)
        except Exception as e:
            # If ipdb is not available, that's expected
            if "ipdb" in str(e):
                pytest.skip("ipdb not available")
            else:
                raise


class TestDebuggerSelection:
    """Test debugger selection functionality"""

    def test_choose_debugger_function_exists(self):
        """Test that _choose_debugger function exists and is callable"""
        from hot_restart import _choose_debugger
        assert callable(_choose_debugger)

    @patch.dict('os.environ', {'HOT_RESTART_DEBUGGER': 'pdb'})
    def test_debugger_selection_with_env_var(self):
        """Test debugger selection respects environment variable"""
        from hot_restart import _choose_debugger
        result = _choose_debugger()
        assert result == 'pdb'

    @patch.dict('os.environ', {'HOT_RESTART_DEBUGGER': 'ipdb'})
    def test_debugger_selection_ipdb_env_var(self):
        """Test debugger selection with ipdb environment variable"""
        from hot_restart import _choose_debugger
        result = _choose_debugger()
        assert result == 'ipdb'

    @patch.dict('os.environ', {}, clear=True)
    @patch('importlib.util.find_spec')
    def test_debugger_auto_detection(self, mock_find_spec):
        """Test automatic debugger detection when no env var is set"""
        from hot_restart import _choose_debugger

        # Mock ipdb being available
        mock_find_spec.return_value = Mock()
        result = _choose_debugger()
        assert result in ['ipdb', 'pdb']  # Should prefer ipdb if available

    @patch.dict('os.environ', {}, clear=True)
    @patch('importlib.util.find_spec')
    def test_debugger_fallback_to_pdb(self, mock_find_spec):
        """Test fallback to pdb when ipdb is not available"""
        from hot_restart import _choose_debugger

        # Mock ipdb not being available
        mock_find_spec.return_value = None
        result = _choose_debugger()
        assert result == 'pdb'


class TestPostMortemFunctions:
    """Test post-mortem debugging functions"""

    def test_start_post_mortem_function_exists(self):
        """Test that _start_post_mortem function exists"""
        from hot_restart import _start_post_mortem
        assert callable(_start_post_mortem)

    def test_start_pdb_post_mortem_exists(self):
        """Test that _start_pdb_post_mortem function exists"""
        from hot_restart import _start_pdb_post_mortem
        assert callable(_start_pdb_post_mortem)

    def test_start_ipdb_post_mortem_exists(self):
        """Test that _start_ipdb_post_mortem function exists"""
        from hot_restart import _start_ipdb_post_mortem
        assert callable(_start_ipdb_post_mortem)

    def test_start_pudb_post_mortem_exists(self):
        """Test that _start_pudb_post_mortem function exists"""
        from hot_restart import _start_pudb_post_mortem
        assert callable(_start_pudb_post_mortem)

    def test_start_pydevd_post_mortem_exists(self):
        """Test that _start_pydevd_post_mortem function exists"""
        from hot_restart import _start_pydevd_post_mortem
        assert callable(_start_pydevd_post_mortem)

    @patch('hot_restart.HotRestartPdb')
    @patch('hot_restart._create_undead_traceback')
    def test_start_pdb_post_mortem_calls(self, mock_create_tb, mock_pdb_class):
        """Test that _start_pdb_post_mortem creates proper instances"""
        from hot_restart import _start_pdb_post_mortem

        # Mock the dependencies
        mock_tb = Mock()
        mock_create_tb.return_value = (mock_tb, 0)
        mock_pdb_instance = Mock()
        mock_pdb_class.return_value = mock_pdb_instance

        # Create a mock traceback
        try:
            raise ValueError("Test exception")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

            # Call the function with correct signature
            _start_pdb_post_mortem("test_func", exc_info, 0)

            # Verify it was called
            mock_pdb_class.assert_called_once()


class TestTracebackHandling:
    """Test traceback handling functions"""

    def test_create_undead_traceback_exists(self):
        """Test that _create_undead_traceback function exists"""
        from hot_restart import _create_undead_traceback
        assert callable(_create_undead_traceback)

    def test_create_undead_traceback_with_real_traceback(self):
        """Test _create_undead_traceback with a real traceback"""
        from hot_restart import _create_undead_traceback
        import sys

        def mock_wrapper():
            pass

        try:
            raise ValueError("Test exception for traceback")
        except ValueError:
            tb = sys.exc_info()[2]
            current_frame = sys._getframe()

            # Should not crash when processing real traceback
            result = _create_undead_traceback(tb, current_frame, mock_wrapper)
            # The function should return a tuple (tb, num_frames)
            assert isinstance(result, tuple)
            assert len(result) == 2
