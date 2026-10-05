# India Drought & Groundwater Watch

**Live site: https://rushikeshay.github.io/India_Drought_Tracker/**

A district-level view of rain, groundwater and drought across India. In India a drought is declared mainly on rainfall, so a district with normal rain and falling groundwater gets no declaration. This site shows both for every district and marks the districts where that happens ("hidden drought").

**This is not an official drought declaration.** It is an independent view built from public government data.

## What it shows

| Layer | Source | Updated |
|---|---|---|
| Rain this season | India Meteorological Department: official district figures, with IMD gridded rainfall as the fallback and for history | Daily |
| Groundwater level | Central Ground Water Board wells, via the National Water Data Portal | Daily |
| Groundwater stress | IN-GRES (CGWB and IIT Hyderabad) | Yearly |
| Drought index | India Drought Monitor, Water and Climate Lab, IIT Gandhinagar | Weekly |

Each district gets one of four categories from rain and groundwater together: Fine, Buffered, Hidden drought or Double drought. Past dates go back to 2000. The definitions, thresholds and limits are on the site's [Methods page](https://rushikeshay.github.io/India_Drought_Tracker/methods.html).

## How it is built

- `pipeline/` downloads the sources and writes the site's data files to `web/data/`.
- `web/` is a static site (plain HTML and JavaScript with D3, no build step), published with GitHub Pages.
- `.github/workflows/refresh.yml` runs `python -m pipeline.run` every day and publishes the result.
- `docs/plan.md` records the design decisions and results; `docs/sources.md` records each source's access details and quirks.

To run it yourself (Python 3.11):

```
pip install -r requirements.txt
python -m pipeline.run                           # refresh the data
python -m unittest discover -s tests -t .        # tests
cd web && python -m http.server 8765             # then open http://localhost:8765/
```

## Contact

Built and maintained by Rushikesh Yashwant Jadhav. To report a wrong figure or suggest a change, [open an issue](https://github.com/Rushikeshay/India_Drought_Tracker/issues) or email rushikesh.y.jadhav@gmail.com.
