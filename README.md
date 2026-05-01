# Gaia

Scripts for downloading and working with [Gaia](https://www.cosmos.esa.int/web/gaia) mission data.

---

## `download_gaia_dr3.py` — Download Gaia DR3 `gaia_source` files

Downloads all (or a subset of) the Gaia DR3 `gaia_source` CSV files from the ESA CDN:

```
https://cdn.gea.esac.esa.int/Gaia/gdr3/gaia_source/
```

### Requirements

```bash
pip install -r requirements.txt
```

### Usage

```
python download_gaia_dr3.py [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `-o`, `--output-dir DIR` | `gaia_dr3_data` | Directory where files are saved |
| `-w`, `--workers N` | `4` | Number of parallel download workers |
| `-n`, `--limit N` | all | Max number of files to download |
| `--dry-run` | — | List files without downloading |
| `--resume` / `--no-resume` | resume enabled | Resume partial / skip complete downloads |

### Examples

```bash
# Download all files (parallel, 4 workers, auto-resume)
python download_gaia_dr3.py

# Save to a custom directory with 8 parallel workers
python download_gaia_dr3.py -o /data/gaia -w 8

# Preview the first 10 files without downloading
python download_gaia_dr3.py --dry-run -n 10

# Download only the first 5 files
python download_gaia_dr3.py -n 5
```
