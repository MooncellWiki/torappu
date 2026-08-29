"""Minimal FastAPI-style dependency injection.

A *dependant* is a callable whose parameters are filled in by a
:class:`Resolver` instead of by the caller. Every parameter must be one of:

* ``param: Annotated[T, Depends(fn)]`` or ``param: T = Depends(fn)`` -- call
  ``fn`` (sync or async; itself a dependant) and inject its result. Results
  are cached per :class:`Resolver`, so a dependency shared by several
  parameters (directly or transitively) runs once per resolution.
* ``param: SomeType`` -- inject the object the resolver was created with for
  that type (``Client``, ``Config``, ...; see
  ``torappu.core.tasks.base.PROVIDED_TYPES``). Subclass annotations match
  too, e.g. ``client: AssetBundleClient`` receives the pipeline ``Client``.

Signatures are analysed eagerly by :func:`analyze`, so a parameter that
cannot be injected fails when the task is registered (at import time), not
when the pipeline reaches it.
"""

import inspect
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, get_args, get_origin, get_type_hints

__all__ = ["Dependant", "Depends", "Param", "Resolver", "analyze"]


class Depends:
    """Marks a parameter as "the result of calling ``dependency``"."""

    __slots__ = ("dependency", "use_cache")

    def __init__(
        self, dependency: Callable[..., Any], *, use_cache: bool = True
    ) -> None:
        if not callable(dependency):
            raise TypeError(f"Depends() expects a callable, got {dependency!r}")
        self.dependency = dependency
        self.use_cache = use_cache

    def __repr__(self) -> str:
        return f"Depends({_describe(self.dependency)})"


@dataclass(frozen=True, slots=True)
class Param:
    """How one parameter of a :class:`Dependant` gets its value.

    Exactly one of ``provided`` (key into the resolver's provided objects) or
    ``depends``/``dependant`` (analysed ``Depends`` marker) is set.
    """

    name: str
    provided: type | None = None
    depends: Depends | None = None
    dependant: "Dependant | None" = None


@dataclass(frozen=True, slots=True)
class Dependant:
    call: Callable[..., Any]
    params: tuple[Param, ...]


def _describe(call: Callable[..., Any]) -> str:
    return getattr(call, "__qualname__", None) or repr(call)


def _type_hints(call: Callable[..., Any]) -> dict[str, Any]:
    target = call.__init__ if inspect.isclass(call) else call
    try:
        return get_type_hints(target, include_extras=True)
    except Exception:
        # e.g. a forward reference to a TYPE_CHECKING-only name somewhere in
        # the signature; the raw annotations are enough as long as the
        # injected parameters themselves resolve.
        return {}


def _match_provider(annotation: Any, provided: tuple[type, ...]) -> type | None:
    if not inspect.isclass(annotation):
        return None
    for candidate in provided:
        if issubclass(candidate, annotation):
            return candidate
    return None


def analyze(
    call: Callable[..., Any],
    provided: Iterable[type],
    *,
    _stack: tuple[Callable[..., Any], ...] = (),
) -> Dependant:
    """Build the dependency tree of ``call``.

    Raises ``TypeError`` for a parameter that is neither marked with
    ``Depends`` nor annotated with one of ``provided``, and for circular
    dependencies.
    """
    provided = tuple(provided)
    if call in _stack:
        chain = " -> ".join(_describe(c) for c in (*_stack, call))
        raise TypeError(f"circular dependency: {chain}")
    stack = (*_stack, call)

    try:
        signature = inspect.signature(call)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"cannot inspect the signature of {_describe(call)}") from exc
    hints = _type_hints(call)

    params: list[Param] = []
    for param in signature.parameters.values():
        if param.kind not in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY):
            raise TypeError(
                f"{_describe(call)}: parameter {param.name!r} must be injectable "
                "by keyword (no *args, **kwargs or positional-only parameters)"
            )

        annotation = hints.get(param.name, param.annotation)
        depends = param.default if isinstance(param.default, Depends) else None
        if get_origin(annotation) is Annotated:
            annotation, *extras = get_args(annotation)
            markers = [extra for extra in extras if isinstance(extra, Depends)]
            if markers:
                if depends is not None:
                    raise TypeError(
                        f"{_describe(call)}: parameter {param.name!r} has Depends() "
                        "both as its default and inside Annotated[...]"
                    )
                depends = markers[-1]

        if depends is not None:
            params.append(
                Param(
                    name=param.name,
                    depends=depends,
                    dependant=analyze(depends.dependency, provided, _stack=stack),
                )
            )
            continue

        if annotation is param.empty:
            raise TypeError(
                f"{_describe(call)}: parameter {param.name!r} has no annotation; "
                "annotate it with a provided type or mark it with Depends(...)"
            )
        provider = _match_provider(annotation, provided)
        if provider is None:
            expected = ", ".join(t.__name__ for t in provided)
            raise TypeError(
                f"{_describe(call)}: cannot inject parameter {param.name!r} "
                f"(annotation {annotation!r}); annotate it with one of {expected} "
                "or mark it with Depends(...)"
            )
        params.append(Param(name=param.name, provided=provider))

    return Dependant(call=call, params=tuple(params))


class Resolver:
    """Resolves dependants against a fixed set of provided objects.

    One resolver is one dependency cache, i.e. one task run.
    """

    def __init__(self, provided: Mapping[type, Any]) -> None:
        self._provided = dict(provided)
        self._cache: dict[Callable[..., Any], Any] = {}

    async def solve_params(self, dependant: Dependant) -> dict[str, Any]:
        """Resolve every parameter of ``dependant``, in declaration order."""
        kwargs: dict[str, Any] = {}
        for param in dependant.params:
            if param.depends is not None and param.dependant is not None:
                kwargs[param.name] = await self._solve_depends(
                    param.depends, param.dependant
                )
            elif param.provided is not None:
                kwargs[param.name] = self._provided[param.provided]
            else:  # pragma: no cover - analyze() never builds such a Param
                raise TypeError(f"unresolvable parameter {param.name!r}")
        return kwargs

    async def solve(self, dependant: Dependant) -> Any:
        """Resolve the parameters and call ``dependant.call`` (awaiting if needed)."""
        result = dependant.call(**await self.solve_params(dependant))
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _solve_depends(self, depends: Depends, dependant: Dependant) -> Any:
        key = depends.dependency
        if depends.use_cache and key in self._cache:
            return self._cache[key]
        value = await self.solve(dependant)
        if depends.use_cache:
            self._cache[key] = value
        return value
