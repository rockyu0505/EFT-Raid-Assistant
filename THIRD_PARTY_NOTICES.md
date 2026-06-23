# Third-Party Notices

EFT Raid Assistant is licensed under the MIT License. The packaged Windows
release also includes third-party libraries, tools, models, and runtime files.
Those components are not relicensed by this project and remain under their
respective upstream licenses.

This notice is a practical summary for the packaged release, not legal advice.
When redistributing modified builds, review the upstream license text for the
exact version you ship.

## Major Bundled Components

| Component | Purpose | License summary |
| --- | --- | --- |
| Python | Application runtime | Python Software Foundation License |
| PySide6 / Qt for Python | Desktop GUI bindings | LGPL/commercial Qt licensing plus third-party notices |
| Qt runtime libraries | Desktop GUI runtime | LGPL/commercial Qt licensing plus third-party notices |
| Shiboken6 | PySide binding support | LGPL/commercial Qt licensing plus third-party notices |
| RapidOCR | OCR pipeline | Apache-2.0 |
| PP-OCR ONNX models bundled by RapidOCR | OCR recognition/detection models | RapidOCR/PaddleOCR model distribution terms; see upstream RapidOCR notices |
| ONNX Runtime | Neural-network inference runtime | MIT |
| OpenCV Python | Image processing dependency | Apache-2.0 |
| NumPy | Numerical array runtime | BSD-3-Clause and bundled third-party licenses |
| Pillow | Image processing | MIT-CMU |
| pytesseract | Python wrapper for Tesseract | Apache-2.0 |
| Tesseract OCR | OCR fallback executable/runtime | Apache-2.0 |
| tessdata language files | Tesseract OCR language data | Apache-2.0 or upstream tessdata terms |
| pynput | Global hotkeys | LGPLv3 |
| mss | Screenshot capture | MIT |
| pywin32 | Windows integration | PSF |
| PyInstaller bootloader/runtime | Windows executable packaging | GPLv2-or-later with PyInstaller bootloader exception |

## Qt / PySide6 Notes

The Windows release bundles Qt/PySide6 dynamic libraries. They are used as
separate runtime libraries and are not owned by this project. Users who need to
exercise rights granted by the applicable Qt open-source licenses should be able
to replace the bundled Qt/PySide6 runtime files with compatible versions.

Qt for Python license details are published by the Qt project:

https://doc.qt.io/qtforpython-6/licenses.html

## Source Data

Item and price data are fetched from the public tarkov.dev GraphQL API and
cached locally for lookup speed. Escape from Tarkov item names, images, and
game terminology belong to their respective rights holders.

EFT Raid Assistant is an independent fan-made utility and is not affiliated
with, endorsed by, or sponsored by Battlestate Games, Escape from Tarkov,
RapidAI, Qt, or tarkov.dev.
