import * as XLSX from "xlsx";
import type { ChecklistItemDetail } from "@/api/compliance";

/**
 * Exports checklist items to .xlsx. `getStatusLabel` returns the display
 * label for a row, or null to exclude that item (e.g. 해당없음/비활성화).
 */
export function exportChecklistToExcel(
  items: ChecklistItemDetail[],
  getStatusLabel: (item: ChecklistItemDetail) => string | null,
  sheetName: string,
  filename: string,
) {
  const rows = items
    .map((item) => ({ item, label: getStatusLabel(item) }))
    .filter((r): r is { item: ChecklistItemDetail; label: string } => r.label !== null)
    .map(({ item, label }) => ({
      문서: item.documents.map((d) => d.doc_type).join(", ") || "-",
      카테고리: item.category_name ?? "미분류",
      항목: item.merged_title,
      진행상황: label,
    }));

  const sheet = XLSX.utils.json_to_sheet(rows);
  sheet["!cols"] = [{ wch: 16 }, { wch: 16 }, { wch: 60 }, { wch: 12 }];

  // Excel sheet names: max 31 chars, no : \ / ? * [ ]
  const safeSheetName = sheetName.replace(/[:\\/?*[\]]/g, "").slice(0, 31) || "Sheet1";
  // Filenames: strip characters invalid on Windows/most filesystems
  const safeFilename = filename.replace(/[\\/:*?"<>|]/g, "").trim() || "export.xlsx";

  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, sheet, safeSheetName);
  XLSX.writeFile(workbook, safeFilename);
}
