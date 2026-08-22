# Questions the live link answers correctly

Checked Aug 22, 2026, 23:00 IST against https://vaani-mu-three.vercel.app
(100K subset, extractive mode). 140 real MSMARCO-XI queries were sent through
/api/ask and compared with their reference answers; 40 came back right. These
are the cleanest of them, plus a few general ones checked by hand. Confidence
is the retrieval score against the 0.85 gate.

## English (type these, or speak them)

| question | answer you should see | conf |
|---|---|---|
| why do babies fight sleep | Many babies fight sleep because they are unable to stay asleep during light sleep. | 0.91 |
| how often should you wax your car | four times a year, or every three months | 0.95 |
| what is the capital of france | Paris is the capital and largest city of France. | 0.89 |
| how many bones are in the human body | over 270 bones | 0.91 |
| what is photosynthesis | the process by which plants, some bacteria and some protists... | 0.94 |
| what is the population of india | about 1.21 billion people | 0.92 |
| what is kansas minimum wage | $7.25 per hour | 0.94 |
| how many calories in fried rice | approximately 228 calories in a 1 cup serving | 0.95 |
| what is a normalized vector | one that has a magnitude (or length) of exactly 1 | 0.93 |
| what is the meaning of aditi | Mother of the gods | 0.93 |
| columbus texas is in what county | Colorado County in southeastern Texas | 0.91 |
| in what region is massachusetts located | the New England region of the northeastern United States | 0.90 |
| who presides over city council | The Mayor presides over the City Council | 0.89 |
| who invented the telephone | alexander graham bell | 0.89 |
| what is the average body temperature | between 97.6 and 99.6 degrees | 0.93 |
| how much is orange county florida sales tax | 6.50% | 0.94 |
| ny times phone number | 1-800-698-4637 | 0.91 |
| cost to install french drain | $10-$30 a linear foot | 0.95 |

## Hindi typed as text

The Hindi text path is the weak one (cross-lingual retrieval, MRR 0.38 on
this subset). Only these three of the forty also came back right when typed
in Hindi:

| Hindi | English it maps to |
|---|---|
| बच्चे सोते समय क्यों लड़ते हैं | why do babies fight sleep |
| आपको अपनी कार को कितनी बार वैक्स करनी चाहिए? | how often should you wax your car |
| न्यूयॉर्क टाइम्स का फोन नंबर | ny times phone number |

Spoken Hindi goes through Sarvam in translate mode and arrives as an English
query, so any row in the English table should work when spoken in Hindi. That
end to end path was not re-checked tonight; the text rows above were.

## Where the facts come from

Nothing is trained. The corpus is ai4bharat/MSMARCO-XI, the Hindi validation
split: 950,721 web passages and 97,941 real Bing queries with reference
answers, machine translated from MS MARCO. About 45% of the queries have no
answer in the corpus on purpose. The live link serves a 100K passage subset
that keeps the positives for 5,003 of those queries. Every answer is a
sentence lifted from a passage, so the facts are Bing era web snippets:
US counties, tuition, taxes, calories, definitions, celebrities.
