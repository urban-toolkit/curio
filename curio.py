import os
from utk_curio.main import main

if __name__ == "__main__":
    os.environ.setdefault("CURIO_DEV", "1")
    main()