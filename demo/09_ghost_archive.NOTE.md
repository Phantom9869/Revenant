# Note on 09_ghost_archive.json

Same question as the run kept in `before_support_check/`, asked again with the per-sentence
citation check on. The model's raw text is in the `raw` field and the verdict for every sentence
in `claims`.

- The install sentence cites the archived docs, and the archived page does contain
  `$ pipenv install requests-html`. It was kept.
- The second sentence cites #241 for `pip install requests-html==0.9.0`. That code span is in #241,
  but only 20% of the sentence's other words are, so the check withheld it. Here the check is
  being conservative: it threw away a sentence that was probably fine. A lexical check
  will do this to paraphrases and to sentences padded with "the records do not specify".

In the earlier run, the 0.9.0 detail was attributed to the archived docs, which do not contain
it. `16_recheck_saved_answers.txt` replays that exact text through the check, which now flags it.
