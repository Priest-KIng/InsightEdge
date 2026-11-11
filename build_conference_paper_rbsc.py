from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.section import WD_SECTION
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from copy import deepcopy
import textwrap
import json

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'InsightEdge_Conference_Paper_Findings.docx'
FIG=ROOT/'insightedge_architecture_rbsc.png'
COVERAGE_RESULT=ROOT/'docs'/'paper_reproducibility'/'enterprise_coverage'/'results.json'
coverage_result=json.loads(COVERAGE_RESULT.read_text(encoding='utf-8'))
ROUTER_CV=ROOT/'docs'/'paper_reproducibility'/'enterprise_coverage'/'router_cv.json'
router_cv=json.loads(ROUTER_CV.read_text(encoding='utf-8'))['cross_validated_compound_clause_router']
FINDINGS_DIR=ROOT/'docs'/'paper_reproducibility'/'score_gated_coverage'
score_gate_cv=json.loads((FINDINGS_DIR/'score_gate_cv.json').read_text(encoding='utf-8'))
score_gate_oof=score_gate_cv['precision_drop_bound_sensitivity']['0.025']
score_gate_external=json.loads((FINDINGS_DIR/'multihop_summary.json').read_text(encoding='utf-8'))
mh_configs=score_gate_external['configurations']
mh_baseline=mh_configs['global_bm25_top8']['overall']
mh_routed=mh_configs['intent_routed_relevance_gated']['overall']
mh_mmr=mh_configs['lexical_mmr_lambda_0.6']['overall']
mh_routed_delta=score_gate_external['paired_differences_vs_global']['intent_routed_relevance_gated']
mh_mmr_delta=score_gate_external['paired_differences_vs_global']['lexical_mmr_lambda_0.6']
mh_direct=score_gate_external['paired_method_comparisons']['mmr_0.6_vs_routed_gate']
coverage_configs=coverage_result['configurations']
baseline_multi=coverage_configs['global_bm25_topk']['by_gold_source_count']['multi_gold_source']
bounded_multi=coverage_configs['bounded_cap2_window_4']['by_gold_source_count']['multi_gold_source']
paired_bounded=coverage_result['paired_bootstrap_differences_vs_global_bm25']['bounded_cap2_window_4']
overall_baseline=coverage_configs['global_bm25_topk']
overall_bounded=coverage_configs['bounded_cap2_window_4']

# Architecture figure drawn as a clean, print-friendly raster diagram.
W,H=1260,610
im=Image.new('RGB',(W,H),'white'); d=ImageDraw.Draw(im)
fontpath=r'C:\\Windows\\Fonts\\arial.ttf'; boldpath=r'C:\\Windows\\Fonts\\arialbd.ttf'
try:
 f=ImageFont.truetype(fontpath,30); fb=ImageFont.truetype(boldpath,34); fs=ImageFont.truetype(fontpath,28)
except: f=ImageFont.load_default(); fb=f; fs=f
navy='#18324B'; blue='#EAF2F8'; teal='#E8F4F0'; gold='#FFF4D8'; gray='#F2F3F5'; edge='#42627D'; ink='#1F2933'
def box(xy,fill,title,lines):
 d.rounded_rectangle(xy,radius=20,fill=fill,outline=edge,width=3)
 x1,y1,x2,y2=xy
 bb=d.textbbox((0,0),title,font=fb); d.text(((x1+x2-(bb[2]-bb[0]))/2,y1+14),title,font=fb,fill=navy)
 yy=y1+65
 for line in lines:
  bb=d.textbbox((0,0),line,font=fs); d.text(((x1+x2-(bb[2]-bb[0]))/2,yy),line,font=fs,fill=ink); yy+=39
def arrow(x1,y1,x2,y2,label=None):
 import math
 d.line((x1,y1,x2,y2),fill=edge,width=5)
 ang=math.atan2(y2-y1,x2-x1); L=19
 p1=(x2-L*math.cos(ang-.48),y2-L*math.sin(ang-.48)); p2=(x2-L*math.cos(ang+.48),y2-L*math.sin(ang+.48))
 d.polygon([(x2,y2),p1,p2],fill=edge)
 if label:
  bb=d.textbbox((0,0),label,font=f); cx=(x1+x2)/2; cy=(y1+y2)/2
  d.rounded_rectangle((cx-(bb[2]-bb[0])/2-7,cy-27,cx+(bb[2]-bb[0])/2+7,cy+6),radius=5,fill='white')
  d.text((cx-(bb[2]-bb[0])/2,cy-25),label,font=f,fill=ink)
# Mark the server-side processing boundary.
d.rounded_rectangle((410,42,1235,568),radius=28,outline='#6B8E7A',width=4)
d.text((435,53),'LOCAL / ORGANIZATION SERVER',font=f,fill='#456B57')
box((35,205,345,435),blue,'Browser client',['File upload and chat','Workspace selection','Answers with citations'])
box((465,145,820,480),teal,'FastAPI + RAG',['Format-aware extraction','Structure-aware chunks','Intent and file-scope routing','Hybrid retrieval + evidence'])
box((945,145,1205,480),gold,'Local services',['Embeddings','ChromaDB vectors','Ollama generation','SQLite state'])
arrow(345,285,465,285)
arrow(820,260,945,260)
arrow(945,390,820,390)
arrow(465,420,345,420)
d.text((45,536),'Default query and generation path stays inside the configured local boundary.',font=f,fill=ink)
im.save(FIG,dpi=(220,220))

doc=Document()
sec=doc.sections[0]
sec.page_width=Inches(8.5); sec.page_height=Inches(11)
sec.top_margin=Inches(.55); sec.bottom_margin=Inches(.55); sec.left_margin=Inches(.66); sec.right_margin=Inches(.66)
sec.header_distance=Inches(.25); sec.footer_distance=Inches(.25)
# The title and author block occupy a single-column opening section; a
# continuous break then starts the two-column body on the same page.
cols=sec._sectPr.find(qn('w:cols'))
if cols is None: cols=OxmlElement('w:cols'); sec._sectPr.append(cols)
cols.set(qn('w:num'),'1')

styles=doc.styles
normal=styles['Normal']; normal.font.name='Times New Roman'; normal.font.size=Pt(9)
normal._element.rPr.rFonts.set(qn('w:eastAsia'),'Times New Roman')
normal.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY
normal.paragraph_format.space_before=Pt(0); normal.paragraph_format.space_after=Pt(3)
normal.paragraph_format.line_spacing=1.0
for sn in ('Heading 1','Heading 2','Heading 3'):
 s=styles[sn]; s.font.name='Times New Roman'; s.font.color.rgb=RGBColor(0,0,0); s._element.rPr.rFonts.set(qn('w:eastAsia'),'Times New Roman')
 s.paragraph_format.keep_with_next=True; s.paragraph_format.space_before=Pt(6); s.paragraph_format.space_after=Pt(2)

def add_run(p,text,bold=False,italic=False,size=None):
 r=p.add_run(text); r.bold=bold; r.italic=italic; r.font.name='Times New Roman'; r._element.rPr.rFonts.set(qn('w:eastAsia'),'Times New Roman')
 if size: r.font.size=Pt(size)
 return r

def set_cell_margins(cell,top=40,start=55,bottom=40,end=55):
 tc=cell._tc; tcPr=tc.get_or_add_tcPr(); mar=tcPr.first_child_found_in('w:tcMar')
 if mar is None: mar=OxmlElement('w:tcMar'); tcPr.append(mar)
 for m,v in [('top',top),('start',start),('bottom',bottom),('end',end)]:
  node=mar.find(qn('w:'+m))
  if node is None: node=OxmlElement('w:'+m); mar.append(node)
  node.set(qn('w:w'),str(v)); node.set(qn('w:type'),'dxa')

# Title and author block: full-width body content in the opening section.
hp=doc.add_paragraph(); hp.alignment=WD_ALIGN_PARAGRAPH.CENTER; hp.paragraph_format.first_line_indent=Inches(0); hp.paragraph_format.space_before=Pt(6); hp.paragraph_format.space_after=Pt(6); hp.paragraph_format.keep_with_next=True
add_run(hp,'Calibrating Source Coverage for Multi Document Retrieval in InsightEdge',size=17)
t=doc.add_table(rows=2,cols=3); t.alignment=WD_TABLE_ALIGNMENT.CENTER; t.autofit=False
for c in t.columns: c.width=Inches(2.39)
authors=[
 ('Usha C.R.','Department of Computer Science and Engineering','Dayananda Sagar Academy of Technology and Management','Bengaluru, India','usha-cse@dsatm.edu.in'),
 ('K Sainath Reddy','Department of Computer Science and Engineering','Dayananda Sagar Academy of Technology and Management','Bengaluru, India','1dt23cs100@dsatm.edu.in'),
 ('Jayanth V Bhat','Department of Computer Science and Engineering','Dayananda Sagar Academy of Technology and Management','Bengaluru, India','1dt23cs080@dsatm.edu.in'),
 ('K Varshith Anjan','Department of Computer Science and Engineering','Dayananda Sagar Academy of Technology and Management','Bengaluru, India','1dt23cs240@dsatm.edu.in'),
 ('Manith Reddy M','Department of Computer Science and Engineering','Dayananda Sagar Academy of Technology and Management','Bengaluru, India','1dt23cs120@dsatm.edu.in')]
for i,a in enumerate(authors):
 cell=t.cell(i//3,i%3); cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER; set_cell_margins(cell,top=20,bottom=20,start=45,end=45)
 p=cell.paragraphs[0]; p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_after=Pt(0); p.paragraph_format.line_spacing=0.9
 add_run(p,a[0],size=8.1)
 for line in a[1:]:
  p.add_run('\n'); add_run(p,line,italic=(line.startswith('Department') or line.startswith('Dayananda')),size=7.2)
for row in t.rows:
 for cell in row.cells:
  tcPr=cell._tc.get_or_add_tcPr(); borders=OxmlElement('w:tcBorders')
  for side in ('top','left','bottom','right','insideH','insideV'):
   e=OxmlElement('w:'+side); e.set(qn('w:val'),'nil'); borders.append(e)
  tcPr.append(borders)


# Start the two-column body directly below the author block.
sec2=doc.add_section(WD_SECTION.CONTINUOUS)
sec2.page_width=Inches(8.5); sec2.page_height=Inches(11)
sec2.top_margin=Inches(.55); sec2.bottom_margin=Inches(.55); sec2.left_margin=Inches(.66); sec2.right_margin=Inches(.66)
sec2.header_distance=Inches(.25); sec2.footer_distance=Inches(.25)
cols=sec2._sectPr.find(qn('w:cols'))
if cols is None: cols=OxmlElement('w:cols'); sec2._sectPr.append(cols)
cols.set(qn('w:num'),'2'); cols.set(qn('w:space'),'360')

# Abstract and paper body.
p=doc.add_paragraph(); p.paragraph_format.first_line_indent=Inches(0); p.paragraph_format.space_after=Pt(4)
add_run(p,'Abstract—',bold=True)
add_run(p,(f'Local document RAG must balance evidence relevance with coverage across files. We present InsightEdge and evaluate a score-gated source-coverage selector whose threshold is chosen by five-fold cross-validation under a bound on gold-document chunk-share loss. On the complete EnterpriseRAG-Bench v1.0.0 archive ({coverage_result["corpus_manifest"]["document_count"]:,} documents), {coverage_result["supported_questions"]} questions were evaluated with annotated supporting document IDs. At context@{coverage_result["index"]["top_k"]}, the out-of-fold routed selector improved document recall by {score_gate_oof["paired_difference_vs_global_bm25"]["document_recall_at_k"]["mean"]:+.4f} (95% CI [{score_gate_oof["paired_difference_vs_global_bm25"]["document_recall_at_k"]["95pct_bootstrap_ci"][0]:+.4f}, {score_gate_oof["paired_difference_vs_global_bm25"]["document_recall_at_k"]["95pct_bootstrap_ci"][1]:+.4f}]) while gold-document chunk share fell by {abs(score_gate_oof["paired_difference_vs_global_bm25"]["chunk_precision_at_k"]["mean"]):.4f}. On an external 2,255-query MultiHop-RAG benchmark, a threshold frozen from the enterprise folds improved routed document recall by {mh_routed_delta["document_recall_at_8"]["mean_difference"]:+.4f}; a lexical MMR baseline performed slightly better, showing the selector is a tradeoff rather than a universal winner. Results concern document-level retrieval only and do not establish answer correctness or citation entailment.'))
p=doc.add_paragraph(); p.paragraph_format.first_line_indent=Inches(0); p.paragraph_format.space_after=Pt(6)
add_run(p,'Keywords—',bold=True,italic=True); add_run(p,'retrieval-augmented generation, local language models, hybrid retrieval, document provenance, evidence-grounded question answering, privacy-preserving systems',italic=True)

def heading(txt,level=1):
 p=doc.add_paragraph(); p.style='Heading 1' if level==1 else 'Heading 2'; p.alignment=WD_ALIGN_PARAGRAPH.CENTER if level==1 else WD_ALIGN_PARAGRAPH.LEFT
 p.paragraph_format.keep_with_next=True
 add_run(p,txt,bold=True,size=9 if level==1 else 8.7)
 return p

def para(txt,first=True):
 p=doc.add_paragraph(); p.paragraph_format.first_line_indent=Inches(.14) if first else Inches(0); p.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY
 add_run(p,txt)
 return p

def subsection(label,txt):
 p=doc.add_paragraph(); p.paragraph_format.keep_with_next=False; p.paragraph_format.first_line_indent=Inches(0)
 add_run(p,label+' ',bold=True,italic=True,size=8.8); add_run(p,txt)
 return p

def add_figure(path,caption,width=3.18):
 p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before=Pt(3); p.paragraph_format.space_after=Pt(0); p.paragraph_format.keep_with_next=True
 p.add_run().add_picture(str(path),width=Inches(width))
 c=doc.add_paragraph(); c.alignment=WD_ALIGN_PARAGRAPH.CENTER; c.paragraph_format.space_before=Pt(1); c.paragraph_format.space_after=Pt(4); c.paragraph_format.keep_together=True
 add_run(c,caption,italic=True,size=7.5)
 return c

def add_fullwidth_figure(path,caption,width=6.85):
 full=doc.add_section(WD_SECTION.CONTINUOUS)
 full.page_width=Inches(8.5); full.page_height=Inches(11)
 full.top_margin=Inches(.55); full.bottom_margin=Inches(.55); full.left_margin=Inches(.66); full.right_margin=Inches(.66)
 cols=full._sectPr.find(qn('w:cols'))
 if cols is None: cols=OxmlElement('w:cols'); full._sectPr.append(cols)
 cols.set(qn('w:num'),'1')
 p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before=Pt(3); p.paragraph_format.space_after=Pt(0); p.paragraph_format.keep_with_next=True
 p.add_run().add_picture(str(path),width=Inches(width))
 c=doc.add_paragraph(); c.alignment=WD_ALIGN_PARAGRAPH.CENTER; c.paragraph_format.space_before=Pt(1); c.paragraph_format.space_after=Pt(4); c.paragraph_format.keep_together=True
 add_run(c,caption,italic=True,size=7.5)
 resumed=doc.add_section(WD_SECTION.CONTINUOUS)
 resumed.page_width=Inches(8.5); resumed.page_height=Inches(11)
 resumed.top_margin=Inches(.55); resumed.bottom_margin=Inches(.55); resumed.left_margin=Inches(.66); resumed.right_margin=Inches(.66)
 cols=resumed._sectPr.find(qn('w:cols'))
 if cols is None: cols=OxmlElement('w:cols'); resumed._sectPr.append(cols)
 cols.set(qn('w:num'),'2'); cols.set(qn('w:space'),'360')
 return c

def small_table(headers,rows,widths,caption,size=6.8):
 t=doc.add_table(rows=1,cols=len(headers)); t.alignment=WD_TABLE_ALIGNMENT.CENTER; t.autofit=False
 for j,w in enumerate(widths): t.columns[j].width=Inches(w)
 for ri,row in enumerate([headers]+rows):
  cells=t.rows[0].cells if ri==0 else t.add_row().cells
  for j,val in enumerate(row):
   cells[j].width=Inches(widths[j]); cells[j].vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
   tcPr=cells[j]._tc.get_or_add_tcPr(); mar=OxmlElement('w:tcMar')
   for side,v in [('top','30'),('bottom','30'),('start','40'),('end','40')]:
    x=OxmlElement('w:'+side); x.set(qn('w:w'),v); x.set(qn('w:type'),'dxa'); mar.append(x)
   tcPr.append(mar); shade=OxmlElement('w:shd'); shade.set(qn('w:fill'),'E7EDF2' if ri==0 else 'FFFFFF'); tcPr.append(shade)
   borders=OxmlElement('w:tcBorders')
   for side in ('top','left','bottom','right','insideH','insideV'):
    e=OxmlElement('w:'+side); e.set(qn('w:val'),'single'); e.set(qn('w:sz'),'4'); e.set(qn('w:color'),'B7C0C8'); borders.append(e)
   tcPr.append(borders); q=cells[j].paragraphs[0]; q.paragraph_format.space_after=Pt(0); q.alignment=WD_ALIGN_PARAGRAPH.LEFT if j==0 else WD_ALIGN_PARAGRAPH.CENTER
   add_run(q,str(val),bold=(ri==0),size=size)
 for row in t.rows:
  trPr=row._tr.get_or_add_trPr(); cs=OxmlElement('w:cantSplit'); trPr.append(cs)
  for cell in row.cells:
   for cp in cell.paragraphs: cp.paragraph_format.keep_with_next=True
 q=doc.add_paragraph(); q.alignment=WD_ALIGN_PARAGRAPH.CENTER; q.paragraph_format.space_before=Pt(1); q.paragraph_format.space_after=Pt(4); q.paragraph_format.keep_together=True; add_run(q,caption,bold=True,size=7.2)
 return t

heading('I. INTRODUCTION')
para('Organizations rely on reports, manuals, presentations, and spreadsheets whose contents are difficult to explore with exact keyword queries. Neural language models can summarize and explain such material, but a model operating without retrieved evidence may produce unsupported details. Sending private files to a hosted service also creates a data-handling boundary that some users cannot accept. Retrieval-augmented generation (RAG) addresses the first problem by retrieving external passages at query time and conditioning generation on them [1]. InsightEdge applies this pattern to a locally operated document workspace.')
para('The engineering problem is broader than connecting a vector database to a chat model. A practical assistant must extract different file types, preserve useful structure, infer whether a user asks for a summary or a precise fact, keep a named-file question from drifting to another source, and expose the evidence used. It must also communicate when retrieval is weak. These requirements motivate an integrated system with transparent routing, source metadata, and a local inference path.')
para('This paper studies a failure in multi-file chat: a relevance-ranked context can over-allocate to one file and omit complementary evidence. Its contributions are (1) InsightEdge’s source-scope contract, applied before generation and citation; (2) a relevance-gated source cap that admits a near-top alternate document only when its lexical score clears a data-selected threshold; and (3) a five-fold threshold-selection study on all annotated EnterpriseRAG-Bench questions followed by a threshold-frozen transfer evaluation on MultiHop-RAG. The selector is evaluated offline with lexical BM25; the production hybrid path is not changed. We report a coverage–relevance tradeoff and do not claim a new neural ranker, universal superiority, or answer-quality gain.')

heading('II. RELATED WORK')
subsection('A. Retrieval-Augmented Generation:', 'Lewis et al. combine parametric generation with a non-parametric document index to support knowledge-intensive tasks [1]. Dense Passage Retrieval shows how learned representations can identify semantically related passages beyond literal term overlap [2]. These methods provide the basic retrieval-and-generation pattern used here.')
subsection('B. Lexical and Hybrid Retrieval:', 'BM25 remains a strong lexical baseline for exact terminology and rare terms [3]. Dense retrieval can help when the query and source use different wording, while lexical matching can recover names, identifiers, and table values. Rank-fusion methods such as reciprocal rank fusion combine ranked lists without requiring their raw scores to share a scale [6]. InsightEdge uses dense and independent BM25-style candidates in its hybrid path; its current implementation is dense-priority with lexical backfill and should not be confused with canonical RRF.')
subsection('C. Query Transformation and Evaluation:', 'Dense Passage Retrieval and sentence-level embedding models support semantic passage matching [2], [4]. Generative passage fusion offers another RAG design point [5]. HyDE generates a hypothetical passage to improve zero-shot dense retrieval [7], and Self-RAG studies explicit retrieval and self-critique decisions in a trained generation framework [8]. InsightEdge exposes optional local query transformation and follow-up retrieval controls; these are engineering options, not reproductions of the original trained methods. RAGAS separates retrieval and generation evaluation [9]. Recent citation work motivates measuring attribution alongside answer relevance [16], [17]. Our fixture evaluator provides retrieval regression measures, while live probes check source scope and refusal behavior without claiming human-judged entailment.')
subsection('D. Diversity and Enterprise Retrieval:', 'Maximal Marginal Relevance (MMR) explicitly trades query relevance against redundancy [18], and recent DF-RAG dynamically adjusts diversity for reasoning-intensive questions [19]. Cluster-based adaptive retrieval also varies context selection using similarity structure [23]. Multi-document context evaluation emphasizes coverage and redundancy alongside relevance [21]. These works establish that adaptive diversity is not new. Our study asks a narrower question: under a fixed eight-chunk budget and document-level labels, can an alternate source be admitted only when its lexical score remains close to the original cutoff, and does a threshold selected on one benchmark transfer to another? We use EnterpriseRAG-Bench v1.0.0 [20] and MultiHop-RAG [22].')

heading('III. DESIGN OBJECTIVES AND SYSTEM BOUNDARY')
subsection('A. Local processing:', 'The default workflow performs extraction, embedding, vector search, and model generation through local services. Documents do not leave the host on the normal query path. That property belongs to the configuration we ship; provider changes, network exposure, logging, backups, or host administration outside the application can weaken it.')
subsection('B. Action-aware retrieval:', 'The system treats a request as an action to route, not only a string to match. Summary requests retrieve representative content; table questions prioritize structured blocks; OCR questions prioritize OCR-marked material; and comparisons can widen their candidate set. A named filename or file type narrows eligible documents before ranking.')
subsection('C. Traceability and abstention:', 'Retrieved chunks retain source identifiers and structural metadata so the interface can show where evidence came from. The backend may withhold an answer when retrieval is empty or heuristic support is weak. A citation identifies retrieved material; it does not prove that every generated claim is entailed by that material.')
subsection('D. Organizational access:', 'Optional account authentication provides sign-in, administrator-managed accounts, and expiring signed sessions. The prototype uses a shared server and workspace-level retrieval boundaries; it does not enforce per-user or per-team document permissions, enterprise SSO, or distributed multi-tenant storage.')
heading('IV. ARCHITECTURE AND METHODOLOGY')
subsection('A. Ingestion and Representation:', 'The browser uploads supported text, PDF, Word, spreadsheet, HTML, EPUB, and PowerPoint files to a FastAPI service. Format-specific loaders extract text and preserve structural cues such as headings, paragraphs, tables, pages, slides, and OCR markers when available. Scanned PDF pages can use a Tesseract OCR fallback when digital extraction yields little text. A structure-aware chunker produces overlapping segments; each indexed chunk carries document and chunk identifiers, source name, offsets, and applicable page, slide, section, table, or OCR metadata. The embedding service maps chunks into the local vector store. ChromaDB persists vectors; SQLite stores authentication, conversation, and ingestion-job state.')
subsection('B. Intent-Aware Retrieval:', 'A deterministic classifier routes greetings and capability questions without document search and recognizes summaries, outlines, tables, OCR questions, comparisons, multi-document synthesis, and factual lookups. Summary requests retrieve a wider set of representative chunks across sources. Structured-data and OCR requests prioritize matching metadata, while ordinary fact questions use hybrid candidates. A document-scope resolver detects named files and common file types, then applies a document identifier or extension filter before retrieval. This design addresses a practical failure mode in multi-file chat: a semantically similar chunk from an unrelated document should not silently answer a file-specific question.')
subsection('C. Grounded Generation and Provenance:', 'Retrieved passages are supplied to the configured Ollama model together with the query and conversation context. The backend streams generated tokens through server-sent events and emits answer metadata and citations. Citation fields are projected from retrieved metadata rather than parsed from generated prose. The answer path rechecks each retrieved chunk against the active metadata filter before generation; the same filtered evidence feeds both the buffered JSON response and the streamed citations. This enforces source-set consistency, but not claim-level entailment. Evidence checks can abstain on empty or weak retrieval; heuristic support is not a proof of factual correctness [16], [17].')
subsection('D. Processing Boundary and Access:', 'In the default configuration, extraction, embedding, vector search, and generation use local services, so document text is not sent to a hosted AI API by the normal query path. This describes the configured data path, not a universal security guarantee: optional providers, network exposure, backups, logs, and host administration remain deployment responsibilities. Optional organization sign-in uses salted PBKDF2-HMAC-SHA256 password hashes and signed, expiring sessions [15]; administrators can provision or disable accounts. User-level document authorization and enterprise SSO are outside the current prototype.')
subsection('E. Scope-Consistent Evidence Routing (SCER):', 'Let A(q) be the allowed document-ID set resolved from an explicit filename or file type; for a workspace-wide request, A(q) is the full workspace. Let R(q) be the chunks admitted to the answer context and C(q) the chunk-level citations returned to the client. SCER requires citations to be drawn from retrieved evidence and retrieved evidence to be contained in the allowed set. InsightEdge resolves A(q), combines its source filter with any intent filter, retrieves candidates, reapplies the filter to returned metadata, and derives citations from the remaining chunks. The buffered and streaming paths invoke the same sequence. This makes source membership auditable; it does not establish that a cited chunk entails every answer claim.')
para('For a file-specific request, every evidence chunk and citation must belong to the selected document. For a multi-document overview, the allowed set intentionally spans the workspace, and the overview selector allocates representative chunks across documents before generation. This distinction avoids both cross-file substitution and over-narrowing broad summary requests.',first=False)
subsection('F. Rank-Bounded Source Coverage (RBSC):', 'Let R=(r1,…,rn) be the ranked candidate list, K the context budget, w a rank window, and c a per-document cap. RBSC scans the first K+w candidates in rank order and selects no more than c chunks per document until K slots are filled. If the window does not supply K chunks, it fills remaining slots from the original top K; the final context is returned in original rank order. In the serving configuration, K=8, c=2, and w=4. This bounded swap policy preserves a fallback to high-ranked chunks while allowing a near-top alternative document into the prompt. It is activated only for requests classified as multi-source; it is not a claim that every long query needs diversity.')
subsection('G. Relevance-Gated Source Cap:', 'The offline score-gated variant applies the same fixed context budget and per-document cap but admits an outside-top-K candidate only when its absolute FTS5 BM25 score is at least α times the score magnitude of the original Kth candidate. It scans a four-rank extension and fills any remaining positions from the original top K. The fixed multi-source intent rule decides whether the selector is applied. For each training fold, α is chosen from {0.75, 0.85, 0.90, 0.95, 0.99} to maximize document recall while keeping gold-document chunk share within a preselected absolute drop from global BM25. We report a 2.5 percentage-point primary bound and 1- and 5-point sensitivity bounds. The ratio is frozen at 0.85 for the independent MultiHop-RAG evaluation. This feature is an evaluation policy and is not enabled in the production hybrid ranker.')
add_figure(ROOT/'docs'/'paper_assets'/'scer_flow.png','Fig. 1. Scope resolution and evidence flow for named-file and workspace-wide requests.',3.25)

# Figure inline in the current text column.
p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before=Pt(3); p.paragraph_format.space_after=Pt(1)
p.add_run().add_picture(str(FIG),width=Inches(3.35))
p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_after=Pt(5); p.paragraph_format.keep_with_next=False
add_run(p,'Fig. 2. InsightEdge client, retrieval service, local stores, and inference boundary.',italic=True,size=7.5)
small_table(['Input class','Extraction and preserved structure'],[['TXT / Markdown','Text, headings, lists, offsets'],['PDF','Text and tables; page markers; optional OCR'],['DOCX / HTML / EPUB','Paragraph or section text, headings'],['CSV / XLSX','Row-oriented content and table metadata'],['PPTX','Slide text, indices, and table content']],[1.02,2.18],'TABLE I. DOCUMENT INPUTS AND STRUCTURE')

small_table(['Intent','Route and candidates','Selection behavior'],[['Overview','Dense; 64','Representative chunks; final 6 or 8'],['Heading/list','Lexical; 64','Heading blocks; final up to 32'],['Table','Lexical; 16','Prioritize table metadata'],['OCR/scanned','Hybrid; 16','OCR metadata and compression'],['Factual','Hybrid; 12','Dense plus lexical candidates'],['Compare / multi-file','Hybrid-rerank; 24','Wider set; optional expansion'],['Greeting/meta','None','No document retrieval']],[.78,.88,1.54],'TABLE II. QUERY INTENTS AND RETRIEVAL ACTIONS',6.4)
small_table(['Metadata','Role in the pipeline'],[['document_id, source','Workspace/file filter and citation label'],['chunk_id, offsets','Chunk identity and source location'],['page / slide / section','Human-readable evidence location'],['block_type, table_used','Structure-aware routing'],['ocr_used','Identify OCR-derived content'],['snippet / rank / score','Evidence inspection in the client']],[1.15,2.05],'TABLE III. CHUNK PROVENANCE FIELDS',6.6)

heading('V. IMPLEMENTATION AND USER WORKFLOW')
para('The application separates the React/Vite client from the Python API and service layer. The client provides workspace selection, multi-file upload with asynchronous job progress, chat streaming, conversation history, and an evidence panel. The API coordinates ingestion, query routing, retrieval, citations, authentication, and health diagnostics. ChromaDB is accessed as a persistent local store, while SQLite uses indexed workspace and job state. Ollama provides model inference through its local HTTP interface [13], while SQLite persists local state [14]. The API and vector-store layers use FastAPI and ChromaDB [11], [12].')
para('The implementation supports multiple file formats, but extraction quality depends on file structure and OCR dependencies. PDF text and tables are extracted directly where possible; OCR is a fallback, not a guarantee of faithful table or diagram interpretation. Optional HyDE, multi-query expansion, parent context, cross-encoder reranking, compression, Self-RAG-style follow-up retrieval, and local PDF vision assistance are configurable and can add latency. They were not all enabled in the evaluated configuration.')
para('When authentication is enabled, passwords are stored as salted PBKDF2-HMAC-SHA256 hashes and sessions are signed and time-limited [15]. Administrators can create and disable accounts. Self-sign-up is disabled by default. These controls authenticate application access but do not create per-user document authorization.')
add_figure(ROOT/'docs'/'paper_assets'/'ui_summary.png','Fig. 3. Workspace overview generated from representative document evidence.',3.18)
add_figure(ROOT/'docs'/'paper_assets'/'ui_citations.png','Fig. 4. Answer with source sections and retrieved evidence in the client.',3.18)
add_figure(ROOT/'docs'/'paper_assets'/'ui_login.png','Fig. 5. Organization sign-in form.',2.2)
add_figure(ROOT/'docs'/'paper_assets'/'ui_admin.png','Fig. 6. Administrator interface for member creation and status.',3.18)
small_table(['Interface','Purpose'],[['POST /api/ingest/files','Upload files; returns async job ID'],['GET /api/ingest/jobs/{id}','Poll ingestion status'],['GET /api/ingest/documents','List indexed workspace sources'],['POST /api/chat/stream','SSE tokens and final citations'],['GET /api/auth/me','Resolve current account'],['/api/auth/users','Admin-only list/create/disable']],[1.22,1.98],'TABLE IV. SELECTED APPLICATION INTERFACES',6.6)
p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(2); p.paragraph_format.space_after=Pt(1); p.paragraph_format.keep_with_next=True; p.alignment=WD_ALIGN_PARAGRAPH.CENTER; add_run(p,'LISTING 1. DOCUMENT SCOPE IS APPLIED BEFORE RETRIEVAL',bold=True,size=7.1)
p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(.06); p.paragraph_format.right_indent=Inches(.04); p.paragraph_format.space_after=Pt(4); p.paragraph_format.keep_together=True; p.alignment=WD_ALIGN_PARAGRAPH.LEFT
r=p.add_run('documents, metadatas, ids, distances = await \\\n  self._retrieve_with_self_rag(question, workspace_id, decision)\ndocuments, metadatas, ids, distances = \\\n  self._filter_retrieval_result(documents, metadatas, ids,\n                                distances,\n                                decision.metadata_filter)\ncitations = self._build_citations(metadatas, ids, documents,\n                                  distances)')
r.font.name='Consolas'; r.font.size=Pt(6.4); r._element.rPr.rFonts.set(qn('w:eastAsia'),'Consolas')

heading('VI. EXPERIMENTAL EVALUATION')
subsection('A. Test strategy and execution:', 'The backend suite covers routing, structured chunking, evidence and provenance, authentication, state storage, API validation, uploads, streaming, CORS, and evaluator metrics. On 12 November 2026 it completed with 67 passing tests and no failures; the only warning came from a third-party dependency. Authentication cases build an isolated SQLite database per test, so account state left on a developer machine cannot affect the outcome. New answer-pipeline regressions inject a near-duplicate file outside the resolved scope and confirm that both the JSON and the streaming responses drop it from the answer context and from the citation list.')
small_table(['Verification','Observed result'],[['Full test suite','67 passed; 0 failed'],['Named-source answer regression','JSON and SSE cite only the resolved file'],['Post-retrieval boundary','Out-of-scope injected chunk removed'],['Authentication tests','Isolated SQLite database per test'],['Prompt probes','Four answer behaviors and one evidence refusal']],[1.28,1.92],'TABLE V. AUTOMATED AND BEHAVIORAL VERIFICATION',6.3)
subsection('B. Fixture benchmark:', 'The fixture benchmark indexed four documents, covering prose, a structured table, OCR-marked text, and citation-rich content, into thirteen chunks, then posed sixteen labeled questions. Six configurations were compared: dense, lexical, hybrid, hybrid with reranking enabled, hybrid with compression, and adaptive routing. Recall@k captures relevant-source retrieval, MRR and nDCG capture ranking quality, and context precision and recall capture source overlap; chunk correctness is scored against expected snippets. Groundedness is a deterministic term-overlap score, not a model or human judgment. Retrieval used BAAI/bge-small-en-v1.5 through sentence-transformers, with twelve candidates, a final context of three chunks, and a maximum similarity distance of 0.65. The evaluator does not generate answers, so its latency figures stop at retrieval.')

# Compact results table; keep it with its caption in the current column.
rows=[['Dense','0.812','0.812','0.812','0.677','0.797','0.479','45.12','91.85'],['Lexical','0.688','0.688','0.688','0.635','0.672','0.552','3.91','4.69'],['Hybrid','0.812','0.812','0.812','0.677','0.797','0.479','47.85','56.29'],['Hybrid + rerank*','0.812','0.812','0.812','0.677','0.797','0.479','45.85','60.53'],['Hybrid + compression','0.812','0.812','0.812','0.677','0.797','0.479','48.03','54.08'],['Adaptive router','0.750','0.750','0.750','0.667','0.750','0.583','47.71','61.71']]
small_table(['Method','Recall','MRR','nDCG','Ctx P','Ctx R','Chunk C','P50','P95'],rows,[.70,.27,.27,.27,.31,.31,.35,.34,.34],'TABLE VI. FIXTURE RETRIEVAL RESULTS (LATENCY IN MS)',6.2)
para('* The rerank-mode configuration had no cross-encoder configured and therefore measures no reranker effect. Citation precision and source correctness equal context precision for this evaluator.',first=False)
small_table(['Query','Dense baseline','Adaptive route'],[['Workspace overview','3 chunks; 3/4 sources; recall 0.75','6 chunks; 4/4 sources; recall 1.00'],['Unsupported weather','0 chunks returned','0 chunks returned']],[.92,1.23,1.23],'TABLE VII. SELECTED QUERY-LEVEL RESULTS',6.0)
para('The adaptive route improves workspace coverage for the explicit overview request, but its aggregate recall, context precision, and latency do not dominate the other configurations. This is a query-specific routing gain, not an overall winner.',first=False)
add_figure(ROOT/'docs'/'paper_assets'/'retrieval_quality_latency.png','Fig. 7. Fixture median retrieval latency by method; context precision is reported in Table VI.',3.2)
subsection('C. Benchmark findings and timing:', 'Dense and hybrid retrieval tied at recall@k 0.812 and context precision 0.677. Lexical retrieval was faster on this run (P50 3.91 ms) but had lower recall (0.688). The adaptive router had the highest chunk correctness (0.583) and returned all four fixture sources for the workspace overview, yet its aggregate recall was 0.750. Ingestion succeeded for all four documents; its P50/P95 was 171.27/4,777.39 ms, with the first embedding call dominating the tail. Retrieval P95 ranged from 4.69 ms lexical to 91.85 ms dense. These single-run measurements do not establish stable speed rankings. The rerank-mode row used no cross-encoder.')

heading('VII. CONTROLLED DOCUMENT-SCOPE STRESS EVALUATION')
para('To isolate source confusion, the evaluator generated 24 one-chunk reports with the same reserve-coefficient wording and a different named site and numeric value in each file. Each question explicitly named one report. We compared identical hybrid top-3 retrieval with and without filename-resolved document-ID filtering; generation was disabled. The unscoped top three always included the target but mixed in two near-duplicate files. The scope-constrained run kept the target in every query and eliminated other-file chunks.')
small_table(['Metric','Unscoped top-3','Scope constrained'],[['Target document recall@3','1.000 (24/24)','1.000 (24/24)'],['Out-of-scope chunk rate','0.667 (48/72)','0.000 (0/24)'],['Scope resolution','n/a','1.000 (24/24)'],['Scope contract pass','n/a','1.000 (24/24)'],['Mean retrieval latency','56.50 ms','52.54 ms']],[1.15,1.08,1.08],'TABLE VIII. NEAR-DUPLICATE DOCUMENT-SCOPE STRESS TEST',6.3)
add_figure(ROOT/'docs'/'paper_assets'/'scope_contract_results.png','Fig. 8. Filename filtering keeps target-document recall at 100% and removes out-of-scope chunks in the controlled test.',3.28)
para('The 0.667 leakage rate is an observed property of this deliberately constructed corpus, not a rate estimate for arbitrary workspaces. Out-of-scope chunk rate is the count of retrieved chunks whose document ID falls outside the allowed set for the query divided by the number of retrieved chunks. The contract pass metric checks that all returned chunk document IDs belong to the resolved allowed set and each citation refers to a returned chunk in that set. Scope filtering preserved recall in this dataset. The small latency difference is descriptive only; hardware contention and run-to-run variation were not controlled.',first=False)
heading('VIII. RANK-BOUNDED SOURCE-COVERAGE EVALUATION')
para((f'We used EnterpriseRAG-Bench v1.0.0 [20], indexing all {coverage_result["corpus_manifest"]["document_count"]:,} text records ({coverage_result["corpus_manifest"].get("unique_document_id_count", "n/a"):,} unique document IDs) into {coverage_result["corpus_manifest"]["chunk_count"]:,} InsightEdge-style chunks. The archive contains {coverage_result["corpus_manifest"].get("duplicate_document_id_instances", "n/a")} duplicate-ID records, which were retained and grouped by their shared gold ID. The public question file contains 500 items; {coverage_result["supported_questions"]} have annotated expected document IDs and were used here, including {baseline_multi["queries"]} questions with more than one distinct gold document. All annotated gold IDs were present. Both the corpus archive and the question file are pinned by SHA-256 in the released reproducibility bundle. Retrieval used SQLite FTS5 BM25 with candidate@{coverage_result["index"]["candidate_k"]} and a fixed context@{coverage_result["index"]["top_k"]}; no language model generated answers in this experiment.'))
coverage_rows=[]
for key,label in [
    ('global_bm25_topk','Global BM25 top-8'),
    ('bounded_cap2_window_4','RBSC (cap 2, window 4)'),
    ('source_cap_2','Unbounded cap 2'),
    ('source_diverse_topk','One chunk per document'),
    ('intent_routed_source_cap_2','Intent-routed cap 2'),
    ('oracle_intent_upper_bound','Gold-label oracle'),
]:
    metrics=coverage_configs[key]['by_gold_source_count']['multi_gold_source']
    coverage_rows.append([label,str(metrics['queries']),f'{metrics["document_recall_at_k"]:.3f}',f'{metrics["complete_document_recall_at_k"]:.3f}',f'{metrics["chunk_precision_at_k"]:.3f}'])
small_table(['Selector','Q','Doc recall','Complete set','Gold-doc chunk share'],coverage_rows,[1.15,.25,.46,.55,.68],'TABLE IX. MULTI-DOCUMENT RETRIEVAL AT FIXED CONTEXT@8',6.0)
window_rows=[]
for window in (0,4,8,12,16,32,64):
    metrics=coverage_configs[f'bounded_cap2_window_{window}']['by_gold_source_count']['multi_gold_source']
    window_rows.append([str(window),f'{metrics["document_recall_at_k"]:.3f}',f'{metrics["complete_document_recall_at_k"]:.3f}',f'{metrics["chunk_precision_at_k"]:.3f}'])
small_table(['Rank window w','Doc recall','Complete set','Gold-doc chunk share'],window_rows,[.86,.68,.82,1.10],'TABLE X. RANK-WINDOW ABLATION ON MULTI-DOCUMENT QUESTIONS',6.2)
add_fullwidth_figure(ROOT/'docs'/'paper_assets'/'rbsc_tradeoff.png','Fig. 9. Recall gains and gold-chunk share reductions relative to BM25. Values are percentage points; high-diversity policies are listed in Table XII.',6.85)
multi_recall_ci=paired_bounded['multi_gold_document_recall_at_k_difference_95pct_bootstrap_ci']
multi_complete_ci=paired_bounded['multi_gold_complete_document_recall_at_k_difference_95pct_bootstrap_ci']
multi_precision_ci=paired_bounded['multi_gold_chunk_precision_at_k_difference_95pct_bootstrap_ci']
para((f'For the bounded cap-2/window-4 policy, multi-document document recall changed by {paired_bounded["multi_gold_document_recall_at_k_difference"]:+.3f} (95% paired bootstrap CI [{multi_recall_ci[0]:+.3f}, {multi_recall_ci[1]:+.3f}]); complete evidence-set recall changed by {paired_bounded["multi_gold_complete_document_recall_at_k_difference"]:+.3f} (CI [{multi_complete_ci[0]:+.3f}, {multi_complete_ci[1]:+.3f}]); and gold-document chunk share changed by {paired_bounded["multi_gold_chunk_precision_at_k_difference"]:+.3f} (CI [{multi_precision_ci[0]:+.3f}, {multi_precision_ci[1]:+.3f}]). Intervals resample questions 5,000 times and are not repeated hardware or model trials. The rank-window sweep shows that w=4 reached the same measured document and complete-set recall as larger windows while retaining a higher gold-document chunk share than w≥8. This is a Pareto observation on this fixed candidate ranking, not a universally optimal threshold.'))
router=coverage_result['intent_router_vs_multi_gold']
para((f'At the deployment threshold, the intent heuristic flagged {router["routed_queries"]} of {coverage_result["supported_questions"]} questions for source coverage; {router["true_positive"]} of those were multi-gold, giving in-sample precision {router["precision"]:.3f} and recall {router["recall"]:.3f} against gold document multiplicity. Because the long-compound rule (at least 25 words plus a second interrogative clause) was chosen by inspecting these same questions, we also ran a five-fold, threshold-selected evaluation. Out-of-fold precision was {router_cv["precision"]:.3f} (95% CI [{router_cv["bootstrap_95pct_ci"]["precision"][0]:.3f}, {router_cv["bootstrap_95pct_ci"]["precision"][1]:.3f}]) and recall {router_cv["recall"]:.3f} (CI [{router_cv["bootstrap_95pct_ci"]["recall"][0]:.3f}, {router_cv["bootstrap_95pct_ci"]["recall"][1]:.3f}]), versus 0.343 and 0.130 for explicit cues alone. The compound-clause rule buys coverage at the cost of false positives, and routing remains exploratory because the feature family and benchmark are shared. The gold-label oracle is an upper bound and is not deployable. The experiment isolates source selection with lexical BM25; InsightEdge production hybrid ranking uses a different candidate order, so the measured gains must be confirmed on that serving path. Gold-document chunk share counts chunks whose document ID is labeled as supporting; it is not passage-level entailment.'))

cv_rows=[]
for label,key in [('All labeled queries','document_recall_at_k'),('Multi-gold subset','multi_gold_document_recall_at_k')]:
    base_key=key
    if label=='All labeled queries':
        old=score_gate_cv['global_bm25_oof_reference'][base_key]
        new=score_gate_oof['out_of_fold_metrics'][base_key]
        diff=score_gate_oof['paired_difference_vs_global_bm25']['document_recall_at_k']
        share_old=score_gate_cv['global_bm25_oof_reference']['gold_document_chunk_share_at_k']
        share_new=score_gate_oof['out_of_fold_metrics']['gold_document_chunk_share_at_k']
        share_diff=score_gate_oof['paired_difference_vs_global_bm25']['chunk_precision_at_k']['mean']
    else:
        old=score_gate_cv['global_bm25_oof_reference'][base_key]
        new=score_gate_oof['out_of_fold_metrics'][base_key]
        diff=score_gate_oof['multi_gold_paired_difference_vs_global_bm25']['document_recall_at_k']
        share_old=score_gate_cv['global_bm25_oof_reference']['multi_gold_chunk_share_at_k']
        share_new=score_gate_oof['out_of_fold_metrics']['multi_gold_chunk_share_at_k']
        share_diff=score_gate_oof['multi_gold_paired_difference_vs_global_bm25']['chunk_precision_at_k']['mean']
    ci=diff['95pct_bootstrap_ci']
    cv_rows.append([label,f'{old:.3f} → {new:.3f}',f'{diff["mean"]:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}]',f'{share_old:.3f} → {share_new:.3f} ({share_diff:+.3f})'])
small_table(['Evaluation slice','Doc recall, BM25 → gate','Paired Δ recall (95% CI)','Gold chunk share, BM25 → gate'],cv_rows,[.90,.66,.90,1.02],'TABLE XI. FIVE-FOLD ENTERPRISERAG THRESHOLD SELECTION',5.7)
para((f'The primary constraint allowed at most a 2.5-point absolute decrease in gold-document chunk share during training-fold selection. The selected ratio was 0.85 in four folds and 0.95 in one. On held-out folds, document recall improved by {score_gate_oof["paired_difference_vs_global_bm25"]["document_recall_at_k"]["mean"]:+.4f} overall (95% paired bootstrap CI [{score_gate_oof["paired_difference_vs_global_bm25"]["document_recall_at_k"]["95pct_bootstrap_ci"][0]:+.4f}, {score_gate_oof["paired_difference_vs_global_bm25"]["document_recall_at_k"]["95pct_bootstrap_ci"][1]:+.4f}]) and by {score_gate_oof["multi_gold_paired_difference_vs_global_bm25"]["document_recall_at_k"]["mean"]:+.4f} on the {score_gate_oof["out_of_fold_metrics"]["multi_gold_queries"]} multi-gold questions (CI [{score_gate_oof["multi_gold_paired_difference_vs_global_bm25"]["document_recall_at_k"]["95pct_bootstrap_ci"][0]:+.4f}, {score_gate_oof["multi_gold_paired_difference_vs_global_bm25"]["document_recall_at_k"]["95pct_bootstrap_ci"][1]:+.4f}]). These are query-bootstrap intervals over out-of-fold predictions, not repeated full retrieval runs. The intent heuristic itself was fixed and had been inspected on this benchmark, so this isolates threshold selection rather than fully independent router development.'))

mh_rows=[]
for key,label in [('global_bm25_top8','Global BM25'),('intent_routed_relevance_gated','Intent-routed gate'),('lexical_mmr_lambda_0.6','Lexical MMR λ=0.6'),('lexical_mmr_lambda_0.8','Lexical MMR λ=0.8'),('rbsc_cap2_window4','RBSC cap-2/window-4'),('source_diverse_top8','One chunk per source')]:
    m=mh_configs[key]['overall']
    mh_rows.append([label,f'{m["document_recall_at_8"]:.3f}',f'{m["complete_evidence_recall_at_8"]:.3f}',f'{m["gold_document_chunk_share_at_8"]:.3f}'])
small_table(['Policy','Doc recall','Complete evidence','Gold chunk share'],mh_rows,[1.16,.48,.70,.78],'TABLE XII. FROZEN-THRESHOLD MULTIHOP-RAG TRANSFER (2,255 ANSWERABLE QUERIES)',5.9)
para((f'The external benchmark contains {score_gate_external["corpus"]["document_count"]} news articles and {score_gate_external["corpus"]["chunk_count"]:,} chunks; 2,255 answerable queries were scored, while 301 null-evidence questions were not used to assess abstention. The EnterpriseRAG-selected ratio of 0.85 was frozen before this evaluation. The intent-routed gate improved document recall by {mh_routed_delta["document_recall_at_8"]["mean_difference"]:+.4f} (95% CI [{mh_routed_delta["document_recall_at_8"]["95pct_bootstrap_ci"][0]:+.4f}, {mh_routed_delta["document_recall_at_8"]["95pct_bootstrap_ci"][1]:+.4f}]) and complete evidence recall by {mh_routed_delta["complete_evidence_recall_at_8"]["mean_difference"]:+.4f} (CI [{mh_routed_delta["complete_evidence_recall_at_8"]["95pct_bootstrap_ci"][0]:+.4f}, {mh_routed_delta["complete_evidence_recall_at_8"]["95pct_bootstrap_ci"][1]:+.4f}]); gold-document chunk share fell by {abs(mh_routed_delta["gold_document_chunk_share_at_8"]["mean_difference"]):.4f}. The lexical MMR implementation uses BM25 relevance with token-Jaccard redundancy, not dense semantic similarity. At λ=0.6 it reached {mh_mmr["document_recall_at_8"]:.3f} document recall and {mh_mmr["gold_document_chunk_share_at_8"]:.3f} chunk share. In a paired comparison against the routed gate, its recall was higher by {mh_direct["metrics"]["document_recall_at_8"]["mean_difference"]:+.4f} (95% CI [{mh_direct["metrics"]["document_recall_at_8"]["95pct_bootstrap_ci"][0]:+.4f}, {mh_direct["metrics"]["document_recall_at_8"]["95pct_bootstrap_ci"][1]:+.4f}]); the chunk-share difference was {mh_direct["metrics"]["gold_document_chunk_share_at_8"]["mean_difference"]:+.4f} (CI [{mh_direct["metrics"]["gold_document_chunk_share_at_8"]["95pct_bootstrap_ci"][0]:+.4f}, {mh_direct["metrics"]["gold_document_chunk_share_at_8"]["95pct_bootstrap_ci"][1]:+.4f}]). Thus, MMR shows a small recall advantage in this paired sample, while chunk share is statistically similar. Source-diverse selection reached higher recall but with a much larger share loss. This cross-dataset result supports transfer of the operating-point idea, not superiority over MMR or state-of-the-art performance.'))

heading('IX. LIVE LOCAL-MODEL SERVICE EVALUATION')
para('A service-level check exercised the RAG service against an isolated three-document workspace and the local phi3:mini model. It was run after the scope-routing fix and did not measure browser or HTTP transport latency. Five prompts covered a named-file summary, generic workspace overview, named fact, document-borne injection attempt, and unsupported topic. The three-document ingest completed successfully; all five expected behaviors matched: four evidence-backed requests were answered, the unsupported current-weather query was refused, named-file citations stayed in scope, and the injected cross-file marker was not disclosed. Each latency is one observation.')
small_table(['Prompt','Result','Cited sources','Latency'],[['Named summary','Answered; 3 supported points','river_plan.txt','7.42 s'],['Workspace overview','Summarized all 3 files','all 3 files','4.63 s'],['Named fact','Answered: 12 plots','food_plan.txt','1.80 s'],['Document injection','Marker not disclosed; scoped','river_plan.txt','5.59 s'],['Unsupported topic','Abstained; no evidence','none','0.11 s']],[.79,1.18,.92,.52],'TABLE XIII. LIVE PHI3:MINI SERVICE PROBES',6.0)
add_figure(ROOT/'docs'/'paper_assets'/'live_local_latency.png','Fig. 10. Wall time for five single-run local-model service probes.',3.2)
para('The post-fix live check addresses the exact failure class that motivated SCER: the named summary and the instruction-bearing document both cited only river_plan.txt, while the unqualified overview intentionally cited all three indexed documents. A generic overview request was answered instead of being rejected for weak lexical overlap. The unsupported weather query remained an evidence-based refusal. These five prompts show the intended routing behavior in this sample; they do not estimate reliability over a broader prompt distribution.',first=False)

heading('X. SECURITY, PRIVACY, AND OBSERVED BEHAVIOR')
subsection('A. Prompt and document inputs:', 'User questions, conversation history, and document passages are untrusted input in prompt construction. The application does not execute document-supplied tools, and path-based ingestion is constrained to the configured directory. Retrieval filters, evidence checks, and explicit refusal behavior reduce the chance that unrelated content supports an answer. Prompt framing alone cannot prevent every injection or hallucination [10].')
subsection('B. Demonstration and live checks:', 'The paper includes interface snapshots showing refusal of an unsupported population question and a request for hidden instructions. In the post-fix phi3:mini probe, the model did not reveal a marker placed in another file, and citations remained limited to the selected document. This is a single controlled prompt, not an adversarial benchmark or security proof. The verified source boundary complements model-level prompt framing; it does not eliminate prompt-injection risks within an allowed document.')
add_figure(ROOT/'docs'/'paper_assets'/'ui_unsupported.png','Fig. 11. Unsupported off-topic request withheld for lack of workspace evidence.',3.18)
add_figure(ROOT/'docs'/'paper_assets'/'ui_injection.png','Fig. 12. Request to reveal hidden instructions and malware steps was refused.',3.18)
subsection('C. Deployment boundary:', 'The documented organization deployment places the frontend, API, vector store, SQLite, and Ollama on one server on a trusted LAN. Remote access needs TLS, firewall or VPN controls, and restricted access to Ollama. The prototype lacks per-user document permissions, SSO, account recovery, lockout, and production orchestration. Sign-in should not be interpreted as document isolation between users.')

heading('XI. DISCUSSION AND LIMITATIONS')
para((f'The full-corpus evaluation shows a measurable but modest operating point: a relevance gate selected under a 2.5-point chunk-share constraint improved out-of-fold document recall, especially on multi-gold questions. The fixed EnterpriseRAG threshold transferred to MultiHop-RAG, where the routed gate improved over BM25 but lexical MMR λ=0.6 did slightly better at nearly the same chunk share. Unrestricted source diversity obtains higher recall at a much larger precision-proxy cost. These results favor treating selection as an explicit tradeoff controlled by the application’s tolerance for context dilution; they do not establish that the proposed gate is the best selector. The separate 24-document near-duplicate test establishes the source-scope contract in a controlled setup, not general retrieval quality.'))
para('In the local model probes, the generic overview, named-file summary, and named fact produced the intended answer class and source set; one unsupported query abstained; and one document-borne cross-file secret instruction did not leak its marker. The experiment uses only five prompts, one small model, three short text files, and one run. Claim-level entailment, broader injection resistance, OCR-heavy files, and ambiguous filename resolution remain unmeasured.')
para('The benchmarks label expected documents, not relevant passages or answer claims. A retrieved chunk from a gold document counts toward gold-document chunk share even if that passage does not support the answer. The selector evaluation uses lexical FTS5 BM25 rather than the serving path’s dense-priority hybrid ranking; it does not generate answers or score citations. The MultiHop null-evidence questions were not scored for abstention. Query-bootstrap intervals measure question-sample uncertainty on fixed rankings, not run-to-run variance. EnterpriseRAG uses a synthetic enterprise corpus; MultiHop-RAG is a much smaller news corpus, so transfer across these two datasets is encouraging but limited. The fixed intent rule was previously inspected on EnterpriseRAG, and the selector remains offline. The next study needs human passage labels, claim-to-citation entailment, end-to-end hybrid evaluation, answer correctness, broader independent domains, repeated runs, and concurrency measurements.')

heading('XII. REPRODUCIBILITY AND FUTURE EVALUATION')
para('The reproducibility bundle records the full-corpus extraction manifest, benchmark hashes, retrieval settings, fold assignments, out-of-fold per-query metrics, paired-bootstrap intervals, and compact per-query results for the independent benchmark. Scripts regenerate the retrieval runs and the cross-validation summaries. The roughly 2.5 GB EnterpriseRAG archive and MultiHop source corpus are not duplicated in the bundle; their official source and SHA-256 digests are recorded. Smoke-run options are provided only for debugging and are not substituted for full-corpus results.')
para('The study is a retrieval-policy evaluation on a public synthetic enterprise benchmark and a separate news benchmark. Its contribution is the calibrated operating-point analysis and its measured tradeoffs, not a claim of general-purpose accuracy, a novel neural retrieval architecture, or publication acceptance. Answer quality and the deployed hybrid path remain to be evaluated.')

heading('XIII. CONCLUSION')
conclusion=para((f'InsightEdge combines local document processing with a source-scope contract that keeps retrieved evidence and citations within the allowed document set. On {coverage_result["supported_questions"]} annotated EnterpriseRAG-Bench questions, five-fold threshold selection under a 2.5-point gold-chunk-share constraint improved out-of-fold document recall by {score_gate_oof["paired_difference_vs_global_bm25"]["document_recall_at_k"]["mean"]:.3f}; the gain was {score_gate_oof["multi_gold_paired_difference_vs_global_bm25"]["document_recall_at_k"]["mean"]:.3f} for multi-gold queries. Freezing the selected threshold on MultiHop-RAG also improved routed retrieval over BM25, although lexical MMR was slightly stronger at a similar gold-chunk share. This supports a reproducible applied-systems result about calibrated source coverage and its limits. Human passage judgments, answer and citation evaluation, and confirmation on the serving hybrid ranker are still needed before making broader claims.'))
conclusion.paragraph_format.keep_together=True

breakp=doc.add_paragraph(); breakp.paragraph_format.space_after=Pt(0); breakp.add_run().add_break(WD_BREAK.COLUMN)
heading('REFERENCES')
refs=[
'[1] P. Lewis et al., “Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks,” in Proc. NeurIPS, 2020. [Online]. Available: https://arxiv.org/abs/2005.11401',
'[2] V. Karpukhin et al., “Dense Passage Retrieval for Open-Domain Question Answering,” in Proc. EMNLP, 2020. [Online]. Available: https://aclanthology.org/2020.emnlp-main.550/',
'[3] S. Robertson and H. Zaragoza, “The Probabilistic Relevance Framework: BM25 and Beyond,” Foundations and Trends in Information Retrieval, vol. 3, no. 4, pp. 333–389, 2009, doi: 10.1561/1500000019.',
'[4] N. Reimers and I. Gurevych, “Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks,” in Proc. EMNLP-IJCNLP, 2019. [Online]. Available: https://aclanthology.org/D19-1410/',
'[5] G. Izacard and E. Grave, “Leveraging Passage Retrieval with Generative Models for Open Domain Question Answering,” in Proc. EACL, 2021. [Online]. Available: https://aclanthology.org/2021.eacl-main.74/',
'[6] G. V. Cormack, C. L. A. Clarke, and S. Büttcher, “Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods,” in Proc. SIGIR, 2009, pp. 758–759, doi: 10.1145/1571941.1572114.',
'[7] L. Gao et al., “Precise Zero-Shot Dense Retrieval without Relevance Labels,” in Proc. ACL, 2023. [Online]. Available: https://aclanthology.org/2023.acl-long.99/',
'[8] A. Asai et al., “Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection,” in Proc. ICLR, 2024. [Online]. Available: https://openreview.net/forum?id=hSyW5go0v8',
'[9] S. Es et al., “RAGAS: Automated Evaluation of Retrieval Augmented Generation,” in Proc. EACL Demo, 2024. [Online]. Available: https://aclanthology.org/2024.eacl-demo.16/',
'[10] OWASP Foundation, “Top 10 for LLM Applications 2025,” 2025. [Online]. Available: https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/',
'[11] FastAPI, “Tutorial: First Steps,” official documentation. [Online]. Available: https://fastapi.tiangolo.com/tutorial/first-steps/',
'[12] Chroma, “Persistent Client,” official documentation. [Online]. Available: https://docs.trychroma.com/reference/python',
'[13] Ollama, “Generate a Completion,” API documentation. [Online]. Available: https://docs.ollama.com/api/generate',
'[14] SQLite, “Write-Ahead Logging,” official documentation. [Online]. Available: https://www.sqlite.org/wal.html',
'[15] NIST, “SP 800-132: Recommendation for Password-Based Key Derivation,” 2010. [Online]. Available: https://csrc.nist.gov/pubs/sp/800/132/final',
'[16] V. Penzkofer and T. Baumann, “Evaluating and Fine-Tuning Retrieval-Augmented Language Models to Generate Text With Accurate Citations,” in Proc. KONVENS, 2024, pp. 57–64. [Online]. Available: https://aclanthology.org/2024.konvens-main.6/',
'[17] J. Buchmann, X. Liu, and I. Gurevych, “Attribute or Abstain: Large Language Models as Long Document Assistants,” in Proc. EMNLP, 2024, pp. 8113–8140, doi: 10.18653/v1/2024.emnlp-main.463.',
'[18] J. Carbonell and J. Goldstein, “The Use of MMR, Diversity-Based Reranking for Reordering Documents and Producing Summaries,” in Proc. 21st ACM SIGIR, 1998, pp. 335–336, doi: 10.1145/290941.291025.',
'[19] S. H. Khan et al., “DF-RAG: Query-Aware Diversity for Retrieval-Augmented Generation,” in Findings of the Association for Computational Linguistics: EACL, 2026, pp. 2873–2894. [Online]. Available: https://aclanthology.org/2026.findings-eacl.150/',
'[20] Onyx, “EnterpriseRAG-Bench,” Dataset v1.0.0, 2026. [Online]. Available: https://github.com/onyx-dot-app/EnterpriseRAG-Bench/releases/tag/v1.0.0.',
'[21] J.-H. Ju, S. Verberne, M. de Rijke, and A. Yates, “Controlled Retrieval-augmented Context Evaluation for Long-form RAG,” in Findings of the Association for Computational Linguistics: EMNLP, 2025, pp. 21102–21121, doi: 10.18653/v1/2025.findings-emnlp.1151.',
'[22] Y. Tang and Y. Yang, “MultiHop-RAG: Benchmarking Retrieval-Augmented Generation for Multi-Hop Queries,” in Proc. COLM, 2024. [Online]. Available: https://arxiv.org/abs/2401.15391',
'[23] Y. Xu et al., “Cluster-based Adaptive Retrieval: Dynamic Context Selection for RAG Applications,” arXiv:2511.14769, 2025. [Online]. Available: https://arxiv.org/abs/2511.14769',
]
for ref in refs:
 p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(.12); p.paragraph_format.first_line_indent=Inches(-.12); p.paragraph_format.space_after=Pt(2); p.paragraph_format.keep_together=True; p.alignment=WD_ALIGN_PARAGRAPH.LEFT
 add_run(p,ref,size=7.3)

# End the two-column references section explicitly so Word balances its final page.
end_section=doc.add_section(WD_SECTION.CONTINUOUS)
end_cols=end_section._sectPr.find(qn('w:cols'))
if end_cols is None:
    end_cols=OxmlElement('w:cols'); end_section._sectPr.append(end_cols)
end_cols.set(qn('w:num'),'2'); end_cols.set(qn('w:space'),'360')

# Remove table borders on author grid; leave only whitespace, as in the reference.
for row in t.rows:
 for cell in row.cells:
  tcPr=cell._tc.get_or_add_tcPr(); borders=OxmlElement('w:tcBorders')
  for side in ('top','left','bottom','right','insideH','insideV'):
   e=OxmlElement('w:'+side); e.set(qn('w:val'),'nil'); borders.append(e)
  tcPr.append(borders)
# Page numbering suppressed; document core properties.
doc.core_properties.title='Calibrating Source Coverage for Multi Document Retrieval in InsightEdge'
doc.core_properties.subject='Local multi-document RAG system with scope contract and rank-bounded source-coverage evaluation'
doc.core_properties.author='InsightEdge Project Team'
for paragraph in list(doc.paragraphs):
    if paragraph.text.strip() == '.':
        paragraph._element.getparent().remove(paragraph._element)
doc.save(OUT)
print(OUT)
print(FIG)
