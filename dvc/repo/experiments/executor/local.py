import logging
import os
from tempfile import mkdtemp
from typing import TYPE_CHECKING, Optional

from funcy import cached_property

from dvc.scm import SCM
from dvc.utils.fs import remove

from ..base import (
    EXEC_BRANCH,
    EXEC_CHECKPOINT,
    EXEC_HEAD,
    EXEC_MERGE,
    EXEC_NAMESPACE,
)
from .base import EXEC_TMP_DIR, BaseExecutor

if TYPE_CHECKING:
    from scmrepo.git import Git

    from dvc.repo import Repo

    from ..base import ExpStashEntry

logger = logging.getLogger(__name__)


class BaseLocalExecutor(BaseExecutor):
    """Base local machine executor."""

    @property
    def git_url(self) -> str:
        root_dir = os.path.abspath(self.root_dir)
        if os.name == "nt":
            root_dir = root_dir.replace(os.sep, "/")
        return f"file://{root_dir}"

    @cached_property
    def scm(self):
        return SCM(self.root_dir)

    def cleanup(self):
        super().cleanup()
        self.scm.close()
        del self.scm


class TempDirExecutor(BaseLocalExecutor):
    """Temp directory experiment executor."""

    # Temp dir executors should warn if untracked files exist (to help with
    # debugging user code), and suppress other DVC hints (like `git add`
    # suggestions) that are not applicable outside of workspace runs
    WARN_UNTRACKED = True
    QUIET = True
    DEFAULT_LOCATION = "temp"

    def init_git(self, scm: "Git", branch: Optional[str] = None):
        from dulwich.repo import Repo as DulwichRepo

        from ..utils import push_refspec

        DulwichRepo.init(os.fspath(self.root_dir))

        refspec = f"{EXEC_NAMESPACE}/"
        push_refspec(scm, self.git_url, refspec, refspec)
        if branch:
            push_refspec(scm, self.git_url, branch, branch)
            self.scm.set_ref(EXEC_BRANCH, branch, symbolic=True)
        elif self.scm.get_ref(EXEC_BRANCH):
            self.scm.remove_ref(EXEC_BRANCH)

        if self.scm.get_ref(EXEC_CHECKPOINT):
            self.scm.remove_ref(EXEC_CHECKPOINT)

        # checkout EXEC_HEAD and apply EXEC_MERGE on top of it without
        # committing
        head = EXEC_BRANCH if branch else EXEC_HEAD
        self.scm.checkout(head, detach=True)
        merge_rev = self.scm.get_ref(EXEC_MERGE)
        self.scm.merge(merge_rev, squash=True, commit=False)

    def _config(self, cache_dir):
        local_config = os.path.join(self.dvc_dir, "config.local")
        logger.debug("Writing experiments local config '%s'", local_config)
        with open(local_config, "w", encoding="utf-8") as fobj:
            fobj.write(f"[cache]\n    dir = {cache_dir}")

    def init_cache(self, dvc: "Repo", rev: str, run_cache: bool = True):
        """Initialize DVC (cache)."""
        self._config(dvc.odb.local.cache_dir)

    def cleanup(self):
        super().cleanup()
        logger.debug("Removing tmpdir '%s'", self.root_dir)
        remove(self.root_dir)

    @classmethod
    def from_stash_entry(
        cls,
        repo: "Repo",
        stash_rev: str,
        entry: "ExpStashEntry",
        **kwargs,
    ):
        tmp_dir = mkdtemp(dir=os.path.join(repo.tmp_dir, EXEC_TMP_DIR))
        try:
            executor = cls._from_stash_entry(repo, stash_rev, entry, tmp_dir)
            logger.debug("Init temp dir executor in '%s'", tmp_dir)
            return executor
        except Exception:
            remove(tmp_dir)
            raise


class WorkspaceExecutor(BaseLocalExecutor):
    pass
