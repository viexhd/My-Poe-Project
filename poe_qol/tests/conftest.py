"""Keep tests away from the real per-user data folder (stash history,
sign-in token): every run gets a throwaway one."""
import os
import tempfile

os.environ["TWICE_CORRUPTED_DATA"] = tempfile.mkdtemp(prefix="tc_data_")
