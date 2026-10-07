"""Dataset catalog exceptions."""


class DatasetCatalogError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class DatasetFileUnavailable(DatasetCatalogError):
    """A shipped dataset's data file that the pip package leaves out could
    not be downloaded (``infrastructure/left_out_files.py``). The message says
    what failed and how to get the file."""

    def __init__(self, message: str):
        super().__init__(message, 502)
