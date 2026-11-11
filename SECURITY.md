# Security

## Reporting a problem

Please report security problems privately through GitHub: open the repository's **Security** tab and choose
**Report a vulnerability**. Do not open a public issue for something that could be exploited.

Include the file or steps that trigger the problem and the MapBarber version (`mapbarber --version`). You can
expect a first reply within a week.

## What to expect from the program

MapBarber reads map files that may come from other people or machines. A damaged or hostile file must end in an
error message: it must not hang the program, crash it, or damage other files. A file that does so is a bug worth
reporting.

Saving goes through a temporary file that replaces the target only after it was written completely, and a
backup of the previous file is kept by default. MapBarber makes no network connections.

## Handling map data

Maps of real sites can reveal the layout of buildings and equipment. Check what a map shows before you publish
or attach it to a bug report; the files in `examples/` and `demo/` are synthetic for that reason.
