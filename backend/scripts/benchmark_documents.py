"""Reproducible parser/OCR benchmark harness; does not invent quality scores."""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
from app.config.settings import get_settings
from app.llm_clients.ollama_client import OllamaClient
from app.parsers.smart_parser import SmartParser
from app.services.model_router import ModelRouter
from app.services.ocr_service import OCRService
from app.utils.chunking import chunk_pages

EXPECTED=("text_20_pages.pdf","scan_20_pages.pdf","mixed_text_scan.pdf","tables.pdf","formulas.pdf")
def main() -> None:
 parser=argparse.ArgumentParser(); parser.add_argument("directory",type=Path); parser.add_argument("--output",type=Path,default=Path("data/benchmarks/latest.json")); parser.add_argument("--with-embedding",action="store_true"); args=parser.parse_args(); settings=get_settings(); router=ModelRouter(OllamaClient(settings.ollama_base_url,settings.ollama_chat_timeout_seconds,settings.ollama_health_timeout_seconds,settings.ollama_retry_count),settings.load_models()); parser_service=SmartParser(OCRService(router))
 results=[]
 for name in EXPECTED:
  source=args.directory/name
  if not source.exists(): results.append({"case":name,"status":"missing"}); continue
  started=time.perf_counter()
  try:
   pages=parser_service.parse(source); chunks=chunk_pages(pages,int(settings.load_config().get("rag",{}).get("chunk_tokens",480)),int(settings.load_config().get("rag",{}).get("chunk_overlap_tokens",80))); embedding_seconds=None
   if args.with_embedding:
    embed_started=time.perf_counter(); [router.embed(chunk.content) for chunk in chunks]; embedding_seconds=round(time.perf_counter()-embed_started,3)
   results.append({"case":name,"status":"ok","total_seconds":round(time.perf_counter()-started,3),"pages":len(pages),"ocr_pages":sum(1 for _,_,method in pages if method=="ocr"),"chunks":len(chunks),"embedding_seconds":embedding_seconds,"retrieval_quality":"requires labelled queries/citations; not inferred automatically"})
  except Exception as error: results.append({"case":name,"status":"error","total_seconds":round(time.perf_counter()-started,3),"error":str(error)[:500]})
 args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8"); print(args.output)
if __name__=="__main__": main()
