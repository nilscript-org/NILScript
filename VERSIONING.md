# NIL Versioning

- **Spec versions:** SemVer. MAJOR = breaking sentence/conformance changes; MINOR = new
  perform-compatible capabilities (new Profiles, new optional fields); PATCH = editorial.
- **Releases are also date-stamped** (MCP pattern): `0.1.0 (2026-06-11)`. Bindings advertise
  the spec version in the envelope (`"nil": "0.1"`); Systems MUST reject majors they don't speak.
- **Profiles version independently** (`services-v1`, `services-v2`); a System advertises
  supported (spec, profile) pairs via `QUERY nil.profiles`.
- **Deprecation:** one MINOR of overlap minimum, with `EVENT` warnings emitted by reference
  implementation when deprecated forms are used.
- **Cadence:** the Steward cuts a dated release at most quarterly, only from features already
  running in wosool (see GOVERNANCE).
