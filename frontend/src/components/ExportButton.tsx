import { useState } from "react";
import html2canvas from "html2canvas";
import jsPDF from "jspdf";
import Spinner from "./Spinner";

interface Props {
  symbol: string;
  sectionIds: string[];
}

export default function ExportButton({ symbol, sectionIds }: Props) {
  const [exporting, setExporting] = useState(false);

  async function handleExport() {
    setExporting(true);
    try {
      const pdf = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });
      const pageWidth = pdf.internal.pageSize.getWidth();
      const margin = 10;
      const contentWidth = pageWidth - margin * 2;
      let yOffset = margin;

      // Title
      pdf.setFontSize(16);
      pdf.setTextColor(255, 255, 255);
      pdf.setFillColor(15, 23, 42); // slate-900
      pdf.rect(0, 0, pageWidth, pdf.internal.pageSize.getHeight(), "F");
      pdf.text(`${symbol} Tearsheet`, margin, yOffset + 6);
      pdf.setFontSize(9);
      pdf.setTextColor(148, 163, 184); // slate-400
      pdf.text(`Generated ${new Date().toLocaleDateString()}`, margin, yOffset + 12);
      yOffset += 20;

      for (const id of sectionIds) {
        const el = document.getElementById(id);
        if (!el) continue;

        const canvas = await html2canvas(el, {
          backgroundColor: "#0f172a",
          scale: 2,
          logging: false,
          useCORS: true,
        });

        const imgData = canvas.toDataURL("image/png");
        const imgHeight = (canvas.height / canvas.width) * contentWidth;

        // Check if we need a new page
        if (yOffset + imgHeight > pdf.internal.pageSize.getHeight() - margin) {
          pdf.addPage();
          pdf.setFillColor(15, 23, 42);
          pdf.rect(0, 0, pageWidth, pdf.internal.pageSize.getHeight(), "F");
          yOffset = margin;
        }

        pdf.addImage(imgData, "PNG", margin, yOffset, contentWidth, imgHeight);
        yOffset += imgHeight + 5;
      }

      pdf.save(`${symbol}_tearsheet_${new Date().toISOString().slice(0, 10)}.pdf`);
    } catch (err) {
      console.error("PDF export failed:", err);
    } finally {
      setExporting(false);
    }
  }

  return (
    <button
      onClick={handleExport}
      disabled={exporting}
      className="text-xs text-slate-400 hover:text-white disabled:opacity-50 transition-colors flex items-center gap-1.5"
    >
      {exporting ? (
        <>
          <Spinner size="sm" className="text-slate-400" />
          Exporting...
        </>
      ) : (
        "Export PDF"
      )}
    </button>
  );
}
