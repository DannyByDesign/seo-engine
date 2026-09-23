# Compatibility aliases

Every skill directory here is a symlink to its canonical phase directory (or shared references).
Actual files live in `01-understand/` through `06-learn/`; do not create new implementations here.
The installer discovers those physical directories directly. These aliases preserve existing
host/plugin discovery and older command paths without duplicating content.
