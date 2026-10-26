# Application third-party assets

These notices apply to the new application. The original vendor folders retain their separate licenses and provenance; see [ASSETS_AND_SD_AUDIT.md](ASSETS_AND_SD_AUDIT.md).

## Space Grotesk

The dashboard bundles three font weights locally under `frontend/public/assets/fonts/`. They were converted from the installed Space Grotesk TTF files into WOFF2 without subsetting or glyph changes. Conversion is a build-time preparation already reflected in the committed assets; users do not need font conversion tools.

Copyright 2020 The Space Grotesk Project Authors. Licensed under the SIL Open Font License 1.1. The complete notice and license are included in [OFL.txt](../frontend/public/assets/fonts/OFL.txt). Source project: [floriankarsten/space-grotesk](https://github.com/floriankarsten/space-grotesk). The app makes no external font requests.

## JavaScript and Python packages

Dependency versions and integrity references are recorded in `frontend/package-lock.json`; Python versions are pinned in `backend/requirements.lock`. Individual packages retain their respective license notices in their distributions. React and React DOM, Vite, FastAPI and Pydantic use their own upstream notices; bundling the application does not relicense them. Lucide icons are supplied through `lucide-react`, whose package includes its ISC license and attribution. USB serial access uses pySerial 3.5 (BSD license; the notice ships in its distribution). Image import traces pictures with OpenCV (`opencv-contrib-python-headless`, Apache License 2.0) and NumPy (BSD license); both ship their notices in their wheels.

The bundled reference installers, archived tools, artwork, STL and vendored Arduino libraries are not part of the new application's served runtime. This notice does not grant additional rights to those original materials.
