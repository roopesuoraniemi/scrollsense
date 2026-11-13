# Clean code design

Design tradition (SOLID, GoF, Simple Design, Clean Architecture) is background,
not a checklist: apply a principle only when it names a concrete problem here.
Prefer the simplest structure that satisfies the two principles below; add
indirection when a real seam appears, not on a hunch.

The code-style limits (body ≤ 9, parameters ≤ 3) exist to surface structure.
Exceeding one means a hidden responsibility or a missing type: extract it, never
cut mechanically. FP and OO are orthogonal; code satisfies both.

## 1. Referential transparency

Same inputs, same output.

- Domain logic is pure. Effects (I/O, time, randomness, logging) live at the
  edges, and a function's place in the architecture shows that it has them.
- Data is immutable. No hidden shared state: module mutables, singleton stores,
  globals.
- An impure method is a command or a query, never both (no `save() -> Saved`);
  its signature tells. Exception: an operation that must be atomic, named so the
  mutation is obvious.

## 2. Polymorphism without source dependency

A caller of `o.f()` doesn't know which `f` runs.

- Seams (boundaries, collaborators replaced or faked) get an interface.
  Concretes are injected, wired at the composition root; policy never imports
  detail.
- Switching on type is polymorphism spelled wrong.
- Dependencies point toward stability, and immutable is not stable: a wide value
  changes with the domain however frozen. What many depend on is an interface
  over behaviour or a small value whose meaning won't change; otherwise narrow
  what callers take.
- An interface with one implementation, few dependents and no boundary is
  speculative. Anticipate only a change you can name.

## Shape

A pure core in a shell of polymorphic seams. A class is an abstraction or an
immutable value with its behaviour, not a bag of procedures. Reach for one when
functions share parameters, a value has invariants, or `f(x)` only makes sense
for one kind of `x`. Use the language's native tools; in Python, `ABC` when you
own the implementations, `Protocol` for shapes others satisfy, frozen
dataclasses for values.

## Self-check

1. Is impurity only at the edges, and visible there?
2. Does any method both mutate and return?
3. Does a switch on type stand in for polymorphism?
4. Is a dict, a tuple or a repeated parameter group standing in for a type?
5. Is an interface speculative, or missing where many depend on behaviour?
6. Does anything stable depend on something volatile, or many things on a wide value?
