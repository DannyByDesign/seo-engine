# Local human writing corpus

The actual writing is checked into this repository: 38 Markdown source files and 373 passages.
No JSON catalog, remote-link lookup or runtime download is needed.

`sources/*.md` contains long-form source writing with basic title, date, genre, tone and content
hash metadata. `passages.md` contains all selected writing directly, with its local source ID
and brief genre/tone labels. The 51 passages suited to automatic packets also carry use and
technique notes. Author identities are not used for selection.

The library spans fiction, memoir, essays, reporting, science, commercial instruction,
product copy and editorial writing. Read longer texts selectively; the sampling command
returns a small, varied packet for the current writing task. Runtime commands never fetch
these sources. Source hashes and passage inclusion checks detect accidental changes.

To extend the library, save actual source prose as another Markdown file with the same small
metadata header, then add exact passages with suitable use/technique notes to `passages.md`.
Keep source prose separate from annotations. Remove navigation, tracking links and download
boilerplate. Review passage usefulness; do not select examples just to increase the count.

The library is English-focused and modern samples lean institutional/technical. Historical
texts provide varied craft examples; their facts, prejudices and period diction are not
instructions for new work. Source notices are retained separately from the writing library.
