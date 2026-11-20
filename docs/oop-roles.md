# Code Architecture: Roles and Their Interaction

Overview of typical units and their responsibilities. Code examples in Python.

For an example overview of how the roles interact, see [code-architecture.drawio](code-architecture.drawio).

---

## 1. Roles

### Entry

| Role                         | Responsibility                                                                          | Does not contain             |
| ---------------------------- | --------------------------------------------------------------------------------------- | ---------------------------- |
| **main**               | Entry point: load configuration, wire objects together, start the flow                  | Business logic               |
| **handler / listener** | React to events (requests, messages, UI events); pass them on to coordinator or service | Flow control, business logic |

### Control

| Role                  | Responsibility                               | Does not contain                      |
| --------------------- | -------------------------------------------- | ------------------------------------- |
| **coordinator** | Flow control: which steps run in which order | Own computations; delegates to others |

Related names: orchestrator, controller, manager.

### Creation and Structure

| Role                           | Responsibility                                                        | Does not contain                           |
| ------------------------------ | --------------------------------------------------------------------- | ------------------------------------------ |
| **factory**              | Object creation: construction, dependencies, choice of implementation | Flow or business logic                     |
| **interface / protocol** | Contracts between components (see section 2)                          | Implementation                             |
| **config**               | Central collection of settings                                        | Logic; constants scattered across the code |

### Business Logic

| Role                     | Responsibility                                                                        | Does not contain                              |
| ------------------------ | ------------------------------------------------------------------------------------- | --------------------------------------------- |
| **function**       | Concrete unit of work: one clearly defined task                                       | Knowledge of the overall flow                 |
| **service**        | Business logic not tied to a single entity; domain-oriented rather than flow-oriented | Ordering of the overall flow (→ coordinator) |
| **model / entity** | Domain objects with their own rules (e.g. `Order`, `Customer`)                    | Storage or transport details                  |
| **validator**      | Validation of inputs and states                                                       | Modification of the validated data            |

### Data and External Access

| Role                                 | Responsibility                                                                         | Does not contain                            |
| ------------------------------------ | -------------------------------------------------------------------------------------- | ------------------------------------------- |
| **repository**                 | Loading and storing data (database, files); encapsulates storage details               | Business rules                              |
| **adapter / gateway / client** | Connection to external systems (APIs, message brokers); translation of foreign formats | Business logic                              |
| **mapper / DTO**               | Conversion between layers; DTOs are plain data containers                              | Behavior (DTO); business decisions (mapper) |

### Cross-Cutting

| Role                      | Responsibility                                                                  | Does not contain                                                 |
| ------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| **utils / helpers** | Domain-agnostic helper functions                                                | Domain specifics; keep small to avoid a dumping ground           |
| **logging**         | Record what happened during a run, for people and for debugging (see section 3) | Data the program needs later (→ return values, `metadata.db`) |

### Python Shape of Each Role

**Rule of thumb:** does the unit have to **remember** something between creation and use (settings, credentials, a path, other objects)?

- **Yes** → `class`: the state goes into `__init__`, the work goes into methods.
- **No** → plain `def`: everything it needs comes in as arguments, the result goes out as the return value.

| Role                                 | Python shape                                                                                                       | Why                                                                                                                    |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| **main**                       | `def main()`                                                                                                     | Runs once from top to bottom; nothing to remember                                                                      |
| **handler / listener**         | `class` (or `def` for simple callbacks)                                                                        | Usually holds the coordinator or service it passes events on to                                                        |
| **coordinator**                | `class` with `__init__` + `run()`                                                                            | Remembers its parts (injected via protocols) between setup and every run                                               |
| **factory**                    | `def create_...()`                                                                                               | Runs once, builds the objects, returns them; nothing to remember. A class only if several variants must be chosen from |
| **interface / protocol**       | `class X(Protocol)` with method bodies `...`                                                                   | A type, not an object: describes methods, contains no code, is never instantiated                                      |
| **config**                     | `@dataclass(frozen=True)`                                                                                        | Plain data container for settings; no behaviour                                                                        |
| **function**                   | `def` (several of them grouped in a module)                                                                      | Stateless unit of work: in → out                                                                                      |
| **service**                    | `class` if it holds dependencies, else a module of `def`s                                                      | Depends on whether it needs repositories/adapters                                                                      |
| **model / entity**             | `@dataclass` with methods for its own rules                                                                      | Data plus the rules that belong to that data                                                                           |
| **validator**                  | `def` (a `class` if configured with rules)                                                                     | Checks input, returns a verdict; usually no state                                                                      |
| **repository**                 | `class` with `__init__` + `get`/`save`/`read_...`                                                        | Remembers where the data lives (path, connection)                                                                      |
| **adapter / gateway / client** | `class` with `__init__` + methods                                                                              | Remembers how to reach the external system (URL, credentials, session)                                                 |
| **mapper / DTO**               | mapper: `def`; DTO: `@dataclass` without methods                                                               | Conversion is stateless; a DTO is only data                                                                            |
| **utils / helpers**            | `def`                                                                                                            | Domain-agnostic, stateless                                                                                             |
| **logging**                    | `logger = logging.getLogger(__name__)` at the top of each module; set up once by `configure_logging()` in main | The standard library already is the abstraction: nothing to create, inject or fake                                     |

#### Class vs. function side by side

```python
# function: plain def, everything comes in as arguments
def to_geotiff(raw: RawImage, tile: Tile) -> GeoTIFF:
    ...                                   # georeferences raw with tile bounds


# repository: class, because it remembers where the data lives
class PolygonFile:
    def __init__(self, path: Path) -> None:
        self.path = path                  # remembered state

    def read_polygons(self) -> list[Polygon]:
        ...                               # uses self.path
```

If the repository were written as a function `read_polygons(path)`, the caller would have to know the path and would be tied to files. As an object, the path is stored inside it; the caller only calls `read_polygons()` and never learns where the data comes from.

#### Class, object, method, function

| Term                        | What it is                                                     | Example                          |
| --------------------------- | -------------------------------------------------------------- | -------------------------------- |
| **class**             | Blueprint for objects                                          | `WmsClient`                    |
| **object** (instance) | One thing built from the blueprint, holding its own data       | `source = WmsClient(url, ...)` |
| **method**            | Function that belongs to a class and works on an object's data | `source.fetch(tile)`           |
| **function**          | Stands alone, holds no data                                    | `to_geotiff(raw)`              |

Calling a class (`WmsClient(...)`) creates an object: Python builds an empty object, runs `__init__` on it, and returns it. `__init__` should only store settings; real work (opening files, HTTP requests) happens later in the methods.

#### Why the factory creates objects but no functions

- **Classes** are blueprints: before use, someone has to build an object from them. That is the factory's job (dashed "creates" arrow in the diagram).
- **Functions** are ready to use as soon as their module is imported. There is nothing to build, so the coordinator imports and calls them directly (solid "calls" arrow, no "creates" arrow).

In Python a function is itself an object, so the factory *could* inject one (`Coordinator(..., planner=plan_tiles)`). This only pays off when the function has to be **swappable**, e.g. two strategies to choose from. Pure business functions rarely need that: tests simply call them with test data, without fakes.

---

## 2. Protocols

A protocol is a **contract** (a type): it lists methods, contains no code and is never instantiated.

**In this architecture only the coordinator uses protocols.** It types its dependencies with them (`ImageSource`, `ImageStore`, `PolygonSource`), so it never knows which concrete class sits behind them. main and the factory work with the concrete classes, and functions receive plain data.

### Protocol vs. ABC (Abstract Base Class)

| Aspect                | `Protocol`                                     | `ABC`                               |
| --------------------- | ------------------------------------------------ | ------------------------------------- |
| Typing                | structural: any class with matching methods fits | nominal: implementations must inherit |
| Checking              | static (mypy, pyright)                           | at runtime, on instantiation          |
| Shared implementation | no                                               | possible                              |

**Rule of thumb:** use `Protocol` for lean contracts and loose coupling. Use `ABC` when shared base logic should be inherited or runtime enforcement is wanted.

### Example

```python
from abc import ABC, abstractmethod
from typing import Protocol


# Protocol: no inheritance; any class with a matching fetch() fits
class ImageSource(Protocol):
    def fetch(self, tile: Tile) -> RawImage: ...

class WmsClient:                          # no base class
    def fetch(self, tile: Tile) -> RawImage: ...


# ABC: implementations must inherit and implement every @abstractmethod
class ImageSourceBase(ABC):
    @abstractmethod
    def fetch(self, tile: Tile) -> RawImage: ...

class WmsClientFromBase(ImageSourceBase): # inheritance required
    def fetch(self, tile: Tile) -> RawImage: ...


# consumer: the coordinator types its dependency with the protocol
class ImageAcquisitionCoordinator:
    def __init__(self, source: ImageSource) -> None:
        self._source = source
```

### Recommendations

- Define protocols **at the consumer**, i.e. in the coordinator's module, and keep them **small**.
- Use a type checker (`mypy`, `pyright`); without one, a protocol is only documentation.

---

## 3. Logging

Logging is **cross-cutting**: every module may log, but no module owns it. It is not a role with its own object: each module writes `logger = logging.getLogger(__name__)`, and only `main` sets up where the messages go, once, via `configure_logging()`. The factory creates no logger, and nothing receives one as a parameter.

### Who logs what

| Role                      | Logs                                          | Level                |
| ------------------------- | --------------------------------------------- | -------------------- |
| main                      | start, settings summary without the password  | INFO                 |
| coordinator               | tiles planned / skipped / failed, run summary | INFO, WARNING, ERROR |
| adapter, repository       | requests, retries, files written              | DEBUG, WARNING       |
| function, factory, config | nothing: return a value or raise              | –                   |

The log is for people. Anything the program needs later goes into a return value (`RunReport`) or `metadata.db`.

### Example

```python
# logging_setup.py: never name it logging.py, that would shadow the standard library
def configure_logging(log_file: Path, overwrite: bool = False) -> None:
    """Console at INFO, file at DEBUG. overwrite=True starts an empty file."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file = logging.FileHandler(log_file, mode="w" if overwrite else "a", encoding="utf-8")
    file.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.basicConfig(level=logging.DEBUG, handlers=[console, file], force=True,
                        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")


# main.py: log_file and log_overwrite come from config
configure_logging(settings.log_file, overwrite=settings.log_overwrite)
```

### Rules for logging

- Use the logger, never `print`.
- **Log or raise, not both**: only the place that handles an error logs it (usually the coordinator, with `logger.exception(...)`).
- Never log secrets: no password, and no URL that contains credentials.
- Append by default (`overwrite=False`), so the log of a crashed run survives the restart. Keep `logs/` git-ignored.
- In tests, check log output with pytest's `caplog` fixture; no fake logger is needed.
