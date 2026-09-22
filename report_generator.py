import logging
from pathlib import Path
from datetime import datetime
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

logger=logging.getLogger(__name__)

def rtl(p):
    p.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    pPr=p._p.get_or_add_pPr()
    pPr.append(OxmlElement("w:bidi"))

def cell(cell,text,bold=False):
    cell.text=""
    p=cell.paragraphs[0]; rtl(p)
    r=p.add_run(str(text or "")); r.font.name="Arial"; r.font.size=Pt(10); r.bold=bold
    cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER

def shade(cell,fill="D9EAF7"):
    tcPr=cell._tc.get_or_add_tcPr(); shd=OxmlElement("w:shd")
    shd.set(qn("w:fill"),fill); tcPr.append(shd)

def page_number(p):
    r=p.add_run()
    a=OxmlElement("w:fldChar"); a.set(qn("w:fldCharType"),"begin")
    b=OxmlElement("w:instrText"); b.set(qn("xml:space"),"preserve"); b.text="PAGE"
    c=OxmlElement("w:fldChar"); c.set(qn("w:fldCharType"),"end")
    r._r.extend([a,b,c])

def hyperlink(p,url,text):
    if not url: p.add_run(text); return
    rid=p.part.relate_to(url,"http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",is_external=True)
    h=OxmlElement("w:hyperlink"); h.set(qn("r:id"),rid)
    r=OxmlElement("w:r"); t=OxmlElement("w:t"); t.text=text; r.append(t); h.append(r); p._p.append(h)

def create_daily_report(items,sources,output_dir="reports",now=None):
    now=now or datetime.now()
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    path=out/f"تقرير_رصد_المهرة_{now:%Y-%m-%d}.docx"
    doc=Document()
    for s in doc.sections:
        s.top_margin=Cm(2); s.bottom_margin=Cm(1.8); s.left_margin=Cm(1.8); s.right_margin=Cm(1.8)
        f=s.footer.paragraphs[0]; f.alignment=WD_ALIGN_PARAGRAPH.CENTER
        rr=f.add_run("تقرير رصد المهرة | صفحة "); rr.font.name="Arial"; rr.font.size=Pt(8); page_number(f)

    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before=Pt(90)
    r=p.add_run("مركز رصد ومتابعة مستجدات محافظة المهرة"); r.bold=True; r.font.name="Arial"; r.font.size=Pt(23)
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r=p.add_run("التقرير الإخباري اليومي"); r.bold=True; r.font.name="Arial"; r.font.size=Pt(31)
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r=p.add_run("موجز الأخبار الآنية"); r.font.name="Arial"; r.font.size=Pt(17)
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before=Pt(35)
    r=p.add_run(f"التاريخ: {now:%Y-%m-%d}"); r.font.name="Arial"; r.font.size=Pt(13)
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r=p.add_run(f"الفترة: 00:00 – {now:%H:%M}"); r.font.name="Arial"; r.font.size=Pt(12)
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r=p.add_run("التوقيت المرجعي: Asia/Aden"); r.font.name="Arial"; r.font.size=Pt(11)
    doc.add_page_break()

    h=doc.add_heading("1. الملخص التنفيذي",1); rtl(h)
    p=doc.add_paragraph(); rtl(p)
    p.add_run(f"يعرض هذا التقرير المواد المنشورة في اليوم الحالي فقط ({now:%Y-%m-%d})، "
              f"من بداية اليوم 00:00 حتى وقت إعداد التقرير. عدد المواد ذات تاريخ نشر موثّق: {len(items)}. "
              "لا تُدرج المواد الأقدم أو المواد التي تعذر التحقق من تاريخ نشرها ضمن موجز اليوم.")

    t=doc.add_table(rows=1,cols=3); t.style="Table Grid"
    for i,x in enumerate(["المؤشر","القيمة","النطاق"]):
        cell(t.rows[0].cells[i],x,True); shade(t.rows[0].cells[i])
    for row in [("أخبار اليوم",len(items),f"00:00 – {now:%H:%M}"),
                ("المصادر النشطة",sum(1 for s in sources if s.get("enabled",1)),"شبكة الرصد")]:
        cs=t.add_row().cells
        for i,x in enumerate(row): cell(cs[i],x,i==0)

    h=doc.add_heading("2. أبرز المستجدات",1); rtl(h)
    if not items:
        p=doc.add_paragraph("لا توجد أخبار منشورة اليوم بتاريخ نشر موثّق حتى لحظة إعداد التقرير."); rtl(p)
    for i,item in enumerate(items,1):
        p=doc.add_paragraph(); rtl(p)
        r=p.add_run(f"{i}. {item.get('title','بدون عنوان')}"); r.bold=True; r.font.name="Arial"; r.font.size=Pt(13)
        for label,value in [("المصدر",item.get("source_name")),
                            ("وقت النشر",item.get("published_at")),
                            ("درجة الصلة بالمهرة",item.get("mahra_score"))]:
            p=doc.add_paragraph(); rtl(p); p.add_run(f"{label}: ").bold=True; p.add_run(str(value or "غير متاح"))
        p=doc.add_paragraph(); rtl(p); p.add_run("الملخص: ").bold=True; p.add_run((item.get("content") or "لا يتوفر ملخص.")[:1200])
        p=doc.add_paragraph(); rtl(p); p.add_run("الرابط: ").bold=True; hyperlink(p,item.get("link",""),item.get("link",""))

    h=doc.add_heading("3. حالة شبكة المصادر",1); rtl(h)
    t=doc.add_table(rows=1,cols=3); t.style="Table Grid"
    for i,x in enumerate(["المصدر","الحالة","أخبار اليوم"]):
        cell(t.rows[0].cells[i],x,True); shade(t.rows[0].cells[i])
    counts={}
    for item in items: counts[item.get("source_name","غير معروف")]=counts.get(item.get("source_name","غير معروف"),0)+1
    for s in sources:
        cs=t.add_row().cells; name=s["name"]
        cell(cs[0],name); cell(cs[1],"نشط" if s.get("enabled",1) else "متوقف"); cell(cs[2],counts.get(name,0))

    h=doc.add_heading("4. منهجية الرصد",1); rtl(h)
    p=doc.add_paragraph(); rtl(p)
    p.add_run("يعتمد النظام تاريخ النشر الحقيقي من RSS/Atom أو من بيانات صفحة الخبر مثل JSON-LD ووسوم النشر. "
              "إذا لم يمكن التحقق من تاريخ النشر فلا تُدرج المادة في أخبار اليوم. "
              "ويُحدد اليوم وفق Asia/Aden وليس وفق توقيت الخادم.")
    p=doc.add_paragraph(); rtl(p); p.add_run(f"وقت إنشاء التقرير: {now:%Y-%m-%d %H:%M:%S} | Asia/Aden")
    doc.save(path)
    return str(path)

