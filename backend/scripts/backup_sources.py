"""Archive original sources and a SHA-256 manifest; does not alter source files."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from app.config.settings import get_settings

def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--output-dir", default="data/backups/sources"); args=parser.parse_args(); root=get_settings().documents_path
    output=Path(args.output_dir); output.mkdir(parents=True,exist_ok=True); archive=output/f"sources-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"; manifest=[]
    with ZipFile(archive,"w",ZIP_DEFLATED) as zip_file:
        for source in root.glob("*/original.*"):
            data=source.read_bytes(); relative=source.relative_to(root); zip_file.writestr(str(relative),data); manifest.append({"path":str(relative),"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)})
        zip_file.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps({"archive":str(archive),"sources":len(manifest)}))
if __name__=="__main__": main()
