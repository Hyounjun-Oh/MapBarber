# Contributing

Bug reports and pull requests are welcome.

## Licensing of contributions

MapBarber is released under the MIT license (see `LICENSE`). By submitting a contribution you agree
that it is provided under the same license, and you confirm that:

- you wrote it yourself, or otherwise have the right to submit it under that license, and
- if your employer or institution has rights to what you write, you have its permission.

Please do not copy code, data, icons or text from other projects into a pull request, even if their
license is permissive. Describe the idea and write it fresh, or add the project as a dependency.

## Before opening a pull request

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                           # core tests
MAPBARBER_GUI_TESTS=1 .venv/bin/pytest     # plus the tests that drive a real window
```

- Comments are in English and only where the code cannot speak for itself.
- New interface text goes into every file in `mapbarber/locales/`; the tests check that no language
  is missing a key.
