# Wood Industry Sites Detection

> **Automated detection of wood industry sites using remote sensing and machine learning.**

[![Status: Work in Progress](https://img.shields.io/badge/status-work%20in%20progress-orange)](#)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)

*Note: This repository is at the **project start phase**. The code, structure, pipelines, and documentation are under active initial development and are subject to significant changes.*

This repository is designed to host pipelines intended to collect remote sensing imagery and leverage this information within machine learning models to automatically detect, classify, and map wood industry sites (such as sawmills, pulp plants, and panel plants) in Germany.

---

## 📌 Project Overview and Objective
Identifying wood industry sites denotes crucial information for monitoring the timber market and allows for designing survey samples to gather empirical data on e.g. wood resource use. This project aims to leverage high-resolution satellite/aerial imagery and machine learning architectures to identify wood industry sites across Germany.

The **main objective is the reliable identification and georeferencing of wood industry sites in Germany** from satellite/aerial imagery.

### Planned Key Features
* **Acquisition:** fetch high-resolution aerial imagery from WMS services for tiles planned from hand-drawn site polygons; store them as GeoTIFF tiles with metadata.
* **Preparation:** cut tiles into chips and convert them into the format the model needs.
* **Training:** train computer vision models for geospatial object detection, e.g. YOLO.
* **Prediction:** apply trained models to new areas and output geo-referenced detections as GIS layers.
* **Review:** people confirm or reject detections before they are used.

**Architecture:** how the modules work together and how the code is structured is described in
[docs/concept.md](docs/concept.md), [docs/oop-roles.md](docs/oop-roles.md) and the
*v3-architecture* tab of [docs/code-architecture.drawio](docs/code-architecture.drawio).

---

## 🏗️ Repository Structure (Target Layout)
*This layout reflects the intended structure and may evolve during initial development.*

```text
wood-industry-sites-detection/
├── data/                       # Local data, never committed [gitignored]
│   ├── raw/                    # Module 1 output: polygon GeoPackage, GeoTIFF tiles, metadata.db
│   ├── processed/              # Module 2 output: training/ and prediction/ data in model format
│   ├── weights/                # Module 3 output: trained models
│   ├── results/                # Module 4 output: detections
│   └── review/                 # Module 5 output: human decisions on the results
├── docs/                       # Architecture concept, coding roles, architecture diagram
├── src/                        # Source code, one package per module
│   ├── acquisition/            # Module 1: fetch and store imagery
│   ├── preparation/            # Module 2: chips and model input
│   ├── training/               # Module 3: model training
│   ├── prediction/             # Module 4: detection on new areas
│   └── review/                 # Module 5: confirm or reject detections
├── configs/                    # Settings: paths, WMS access, logging
├── authentification/           # Credentials, e.g. WMS account and password [gitignored]
├── logs/                       # One log file per module [gitignored]
├── tests/                      # Unit tests
├── requirements.txt            # Python dependencies
├── LICENSE                     # MIT License
└── README.md                   # Project documentation
```

The package path is still open: flat as shown, or below a common package (e.g. `src/woodsites/`); see [concept.md §5](docs/concept.md#5-open-decisions).

---

## ⚙️ Getting Started

### Prerequisites
* Python … or higher
* …

### Installation (Initial Setup)
1. **Clone the repository:**
   ```bash
   git clone https://github.com/TI-Wood-Resource-Monitoring/wood-industry-sites-detection.git
   cd wood-industry-sites-detection
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install the dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

---

## 🚀 Usage (Draft Workflows)

### 1. Acquisition
Plans tiles from the site polygons, fetches each tile from the WMS, saves it as a GeoTIFF and records it in `metadata.db`. Each run ends with a summary (fetched, skipped, failed).
```bash
# Workflow example to be defined
```

### 2. Preparation
…
```bash
# Workflow example to be defined
```

### 3. Training
…
```bash
# Workflow example to be defined
```

### 4. Prediction
…
```bash
# Workflow example to be defined
```

### 5. Review
…
```bash
# Workflow example to be defined
```

---

## 📊 Model Performance & Results
Summary of the model metrics:
… *(Evaluation benchmarks will be added once initial models are trained)*

---

## 🗺️ Roadmap
1. **Architecture:** design of the system and of Module 1 (Acquisition). *In progress.*
2. **Module 1 · Acquisition:** build and test. *Planned.*
3. **Modules 2–5:** plan and build, one after another. *Later.*

---

## 🤖 AI Assistance Disclaimer
**This entire project uses the support of artificial intelligence (AI).** Final verification, scientific validity, and domain-specific integration remain managed and validated by the contributors to this repository.

---

## 📜 License
See LICENSE for more information.

---

## 📞 Contact
@SGlasenapp (sebastian.glasenapp@thuenen.de)
