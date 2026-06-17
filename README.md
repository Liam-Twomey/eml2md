# EML to Markdown Converter

This tool converts email files (`.eml`) to Markdown format (`.md`) while
preserving the email thread structure, extracting attachments, and intelligently
removing duplicate emails in threads.

## Features

- Converts `.eml` files to Markdown format
- Preserves email thread structure using multiple methods:
  - Standard RFC822 embedded message detection
  - Pattern matching to detect quoted emails in the body text
  - SimHash-based deduplication to remove redundant email content
- Extracts and saves attachments
- Organizes content in chronological order (oldest-to-newest or newest-to-oldest)
- Provides a CLI interface to convert files in-place.

## Installation

__Prerequisites:__ Install Python 3.10+ and [uv](https://docs.astral.sh/uv/
getting-started/installation/) (preferred) or [pipx](https://pipx.pypa.io/
stable/how-to/install-pipx/)

```shell
# preferred
uv tool install git+https://github.com/Liam-Twomey/eml2md
# alternate
pipx install git+https://github.com/Liam-Twomey/eml2md
```

## Usage

`eml2md [args] emailfile.eml emailfile2.eml`

This will create new folders `emailfile` and `emailfile2` in the parent
directory of the `.eml` files, containing the markdown files and attachments.


### Command Line Options

| Option | Shortcut | Description |
|--------|----------|-------------|
| `--newest-first` | `-n` | Sort emails from newest to oldest in the markdown file (default is oldest to newest) |
| `--dedup-threshold VALUE` | `-t VALUE` | Set the similarity threshold for deduplication (default is 8, higher values mean more aggressive deduplication) |
| `--verbose` | `-v` | Print all available info messages. |
| `--quiet`   | `-q` | Print only warnings and errors. |

## Thread Detection and Deduplication

The tool uses three complementary methods to handle email threads:

1. **Embedded Messages**: Detects properly formatted `message/rfc822` parts in
   multipart emails.

2. **Pattern Matching**: Analyzes the email body text to find patterns
   indicating quoted emails such as:
   - Outlook format: "From: ... Sent: ... To: ... Subject: ..."
   - Reply format: "On [date], [person] wrote:"
   - Gmail format: "On [date] at [time], [person] wrote:"

3. **SimHash Deduplication**: Uses content-based hashing to identify and remove
   duplicate emails, even when formatting differs:
   - Creates a fingerprint for each email that preserves similarity
   - Compares emails using Hamming distance between fingerprints
   - Removes duplicates while prioritizing newer emails

### How SimHash Deduplication Works

The SimHash algorithm:
1. Extracts features from the email (sender, subject, key content lines)
2. Creates a 64-bit fingerprint that preserves content similarity
3. Compares fingerprints using Hamming distance (bit differences)
4. Groups similar emails and keeps only the most representative one

The default threshold of 8 bits (out of 64) works well for most emails, but you
can adjust it with the `--dedup-threshold` parameter. Higher values will be
more aggressive in identifying duplicates.

## Output Format

The generated Markdown file includes:

- Email thread organized chronologically
- Metadata for each email (date, from, to, cc, subject)
- Email content
- Links to extracted attachments

## Example

```markdown
# Email Thread

## Email 1

**Date**: 2023-01-15 14:32:45

**From**: sender@example.com

**To**: recipient@example.com

**Subject**: Example Subject

### Content

This is the content of the email.

### Attachments

- [document.pdf](document.pdf)

---

## Email 2

...
```

## Requirements

- Python >= 3.10
- email-validator >= 2.0.0
- python-dateutil >= 2.8.2

## Project Layout 

```
.
├── pyproject.toml  # Dependencies and packaging information
├── README.md       # Project information and instructions
└── src             # Source code directory
    ├── eml2md.py   # The processing code
    └── __init__.py # Version information and initialization info
```

## Limitations

- The tool is designed for English-language emails
- Complex HTML formatting may be simplified in the conversion process
- Pattern matching depends on email client formatting and may not detect all
  thread styles
- Deduplication thresholds may need adjustment for your specific emails
- Very short emails might be incorrectly identified as duplicates (adjust
  threshold if needed)

## Differences from the parent repo

- Switched path parsing from `os.path` to `pathlib.Path`
- Switched input mechanism to be entirely CLI-based and operating in current
  directory, rather than needing files to be copied into the project directory
- Simplified filename parsing and file loading
- Set up for use with package managers by:
    - Reorganizing file structure
    - Creating `pyproject.toml` to replace `requirements.txt`
    - Defining script behavior

## License

This project is licensed under the MIT License (refer to `LICENSE.txt`)
