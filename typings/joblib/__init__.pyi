"""Type stub for the part of joblib this project uses.

joblib ships no type information, so strict pyright reports the import itself
("Stub file not found for joblib") and every call through it as partially
unknown. Only the two persistence functions main.py calls are declared here;
declare any other joblib function the same way before using it.
"""
from os import PathLike
from typing import IO, Any, Literal

def dump(
    value: object,
    filename: str | PathLike[str] | IO[bytes],
    compress: bool | int | str | tuple[str, int] = ...,
    protocol: int | None = ...,
) -> list[str]: ...
def load(
    filename: str | PathLike[str] | IO[bytes],
    mmap_mode: Literal["r+", "r", "w+", "c"] | None = ...,
    ensure_native_byte_order: bool | Literal["auto"] = ...,
) -> Any: ...
