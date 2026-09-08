"""Chorus — the Agience tool surface: seven tektons, each independently deployable.

Crystal routes, ember runs, chorus is the tool surface. Each tekton constructs its own server auth,
signs with its own identity, and imports no sibling tekton.

The import name is `agience_chorus`, QUALIFIED — it says whose it is. An unqualified `chorus` would
claim a common word in the global import namespace, which is how a package ends up shadowing, or
shadowed by, something unrelated: this repository hit exactly that during the packaging work, when
an `agience` package belonging to another project made `agience.chorus` unresolvable.

Each tekton is a subpackage: `agience_chorus.aria`, `.sage`, `.astra`, `.lumen`, `.iris`,
`.ophan`, `.seraph`.
"""
