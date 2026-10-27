# Note on 09_ghost_archive.json

The first sentence is supported by the archived page (it contains `$ pipenv install requests-html`).

The second sentence is **not**. The archived text contains no "0.9.0"; that number comes from a
tracker comment (#241 was among the retrieved evidence), but the model cited the archive for it.

Revenant's citation check only verifies that each cited ref was among the retrieved evidence. It does
not verify that the cited document actually supports the sentence. This output is kept unedited as a
known limitation; per-sentence support checking is on the roadmap.
