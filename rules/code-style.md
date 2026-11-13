# Code style

## Types

Use the type system fully: annotate every parameter and return type, and
prefer specific types over permissive ones (`list[User]`, not `list`;
`Result<Config, ConfigError>`, not a `dict` that might hold an error). In
gradually-typed languages, types are part of the interface.

- Module boundaries are always typed. Internal helpers too, unless
  inference is idiomatic (Rust `let`, Go `:=`, Swift `let`).
- `Any`, `unknown`, `interface{}`, `object` only at genuine edges
  (deserialization, reflection and plugin loading, interop). Elsewhere a
  type is missing; polymorphism goes through an interface, not `Any`.
- Python: structured data is a named, typed class — `@dataclass(frozen=True)`,
  `NamedTuple`, `pydantic.BaseModel` — never an untyped dict or tuple.
  Interfaces are `Protocol` or `ABC` per clean-code-design.

## Functions

Hard limits, not targets:

- Body ≤ 9 statements. Signature, docstring, blanks and comments don't
  count. Nested functions and lambdas count toward the enclosing body.
- Parameters ≤ 3. `self`/`cls` don't count; positional, keyword-only and
  defaulted all do. `*args`/`**kwargs` only when forwarding to an external
  API at a boundary.
- Over either limit, the fix is structural (see clean-code-design): split
  by responsibility or extract the type the parameters describe. Never cut
  a body mechanically at statement 9 or bundle parameters into an untyped dict.

## Documentation

A comment or docstring that explains *what* code does is a failure to say
it in code: rename, extract, or introduce a type until it's unnecessary.
Two things legitimately remain — the public contract (what a caller may
rely on) and *why* (constraints, workarounds, decisions) — nothing else.

- Public modules, classes, functions, methods: always. State what it does,
  expects, returns, raises, and anything the signature can't say
  (ordering, idempotence, blocking, cost).
- Protected (`_name`): only the subclass contract — when it's called, what
  it must return, what it may not do.
- Private (`__name`): none by default. At most one line, for an invariant
  or caveat the name can't carry. If it needs more, the name is wrong, it
  does too much, or it's really public.
- A docstring longer than its body belongs on the public caller or in the
  return type.

## Visibility

Use the narrowest visibility available. It's part of the contract:
widening is cheap, narrowing breaks callers.

- `protected` is a commitment to subclasses. Use it only when inheritance
  is the intended extension mechanism; otherwise compose.
- Python, three tiers: `__name` private (name mangling is intended — it's
  what gives "private" teeth), `_name` protected, bare name public. This
  deliberately differs from PEP 8; follow it without comment. Never use
  `_name` to mean private.
- Expose fields via `@property`, not `get_x()`/`set_x()`, only when a
  caller needs them, and getter-only unless external mutation is genuinely
  required. A bare attribute can become a property later with no call-site
  changes, so don't add accessors in anticipation.
- In Rust, Go, and other restrict-by-default languages, don't export
  without a reason.

A method that's hard to test because it's private usually wants to be its
own publicly-tested unit, not wider visibility.
