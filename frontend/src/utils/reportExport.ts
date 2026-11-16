import * as XLSX from 'xlsx'
import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'

export interface ReportKpi {
  label: string
  value: string | number
  sublabel?: string
}

export interface ReportTableColumn {
  header: string
  key: string
  align?: 'left' | 'right' | 'center'
}

export interface ExportReportOptions {
  title: string
  subtitle: string
  periodText: string
  kpis?: ReportKpi[]
  columns: ReportTableColumn[]
  rows: Array<Record<string, unknown>>
  summaryRow?: Record<string, unknown>
  orientation?: 'portrait' | 'landscape'
  filenamePrefix?: string
}

export interface MultiSheetExportOptions {
  title: string
  periodText: string
  sheets: Array<{
    sheetName: string
    columns: ReportTableColumn[]
    rows: Array<Record<string, unknown>>
  }>
  filenamePrefix?: string
}

export function exportReportToExcel(options: ExportReportOptions) {
  const { title, subtitle, periodText, kpis = [], columns, rows, summaryRow, filenamePrefix = 'Report' } = options
  const wb = XLSX.utils.book_new()

  // Build grid data
  const aoa: (string | number)[][] = []

  // Header Title
  aoa.push(['SHIVA PRINTS - MANAGEMENT REPORT'])
  aoa.push([title.toUpperCase()])
  aoa.push([`Period: ${periodText} | Generated: ${new Date().toLocaleString('en-IN')}`])
  if (subtitle) aoa.push([subtitle])
  aoa.push([])

  // KPIs row if present
  if (kpis.length > 0) {
    aoa.push(['KEY PERFORMANCE INDICATORS'])
    const kpiLabels = kpis.map((k) => k.label)
    const kpiValues = kpis.map((k) => k.value)
    aoa.push(kpiLabels)
    aoa.push(kpiValues)
    aoa.push([])
  }

  // Table Headers
  const tableHeaders = columns.map((col) => col.header)
  aoa.push(tableHeaders)

  // Table Data Rows
  for (const row of rows) {
    const rowValues = columns.map((col) => {
      const val = row[col.key]
      if (val === null || val === undefined) return '—'
      if (typeof val === 'number') return val
      return String(val)
    })
    aoa.push(rowValues)
  }

  // Summary Row if present
  if (summaryRow) {
    const summaryValues = columns.map((col, idx) => {
      if (idx === 0) return 'TOTAL / SUMMARY'
      const val = summaryRow[col.key]
      if (val === null || val === undefined) return ''
      return typeof val === 'number' ? val : String(val)
    })
    aoa.push(summaryValues)
  }

  const ws = XLSX.utils.aoa_to_sheet(aoa)

  // Column width calculations
  const colWidths = columns.map((col, idx) => {
    let maxLen = Math.max(col.header.length, 12)
    for (const r of rows) {
      const cell = String(r[col.key] ?? '')
      if (cell.length > maxLen) maxLen = Math.min(cell.length, 45)
    }
    return { wch: maxLen + 2 }
  })
  ws['!cols'] = colWidths

  XLSX.utils.book_append_sheet(wb, ws, title.slice(0, 31) || 'Report')

  const dateStr = new Date().toISOString().slice(0, 10)
  const filename = `LibinPrints_${filenamePrefix.replace(/\s+/g, '_')}_${dateStr}.xlsx`
  XLSX.writeFile(wb, filename)
}

export function exportComprehensiveWorkbookToExcel(options: MultiSheetExportOptions) {
  const { title, periodText, sheets, filenamePrefix = 'Comprehensive_Report' } = options
  const wb = XLSX.utils.book_new()

  for (const sheet of sheets) {
    const aoa: (string | number)[][] = []
    aoa.push([`SHIVA PRINTS - ${sheet.sheetName.toUpperCase()}`])
    aoa.push([`Period: ${periodText} | Generated: ${new Date().toLocaleString('en-IN')}`])
    aoa.push([])

    const tableHeaders = sheet.columns.map((c) => c.header)
    aoa.push(tableHeaders)

    for (const row of sheet.rows) {
      const rowValues = sheet.columns.map((col) => {
        const val = row[col.key]
        if (val === null || val === undefined) return '—'
        return typeof val === 'number' ? val : String(val)
      })
      aoa.push(rowValues)
    }

    const ws = XLSX.utils.aoa_to_sheet(aoa)
    ws['!cols'] = sheet.columns.map(() => ({ wch: 18 }))
    const validSheetName = sheet.sheetName.replace(/[\\/?*[\]]/g, '').slice(0, 30)
    XLSX.utils.book_append_sheet(wb, ws, validSheetName)
  }

  const dateStr = new Date().toISOString().slice(0, 10)
  const filename = `LibinPrints_${filenamePrefix.replace(/\s+/g, '_')}_${dateStr}.xlsx`
  XLSX.writeFile(wb, filename)
}

export function exportReportToPdf(options: ExportReportOptions) {
  const {
    title,
    subtitle,
    periodText,
    kpis = [],
    columns,
    rows,
    summaryRow,
    orientation = 'landscape',
    filenamePrefix = 'Report',
  } = options

  const doc = new jsPDF({
    orientation,
    unit: 'pt',
    format: 'a4',
  })

  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()

  // Top header banner
  doc.setFillColor(30, 41, 59) // slate-800
  doc.rect(0, 0, pageWidth, 55, 'F')

  // Company Brand
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.setTextColor(255, 255, 255)
  doc.text('SHIVA PRINTS', 30, 26)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(203, 213, 225)
  doc.text('Commercial Printing ERP & Management Analytics', 30, 42)

  // Document Title & Generation Meta
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(12)
  doc.setTextColor(255, 255, 255)
  doc.text(title.toUpperCase(), pageWidth - 30, 26, { align: 'right' })

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  doc.setTextColor(226, 232, 240)
  doc.text(`Period: ${periodText} | Generated: ${new Date().toLocaleDateString('en-IN')}`, pageWidth - 30, 42, { align: 'right' })

  let currentY = 75

  // Subtitle / Executive description
  if (subtitle) {
    doc.setFont('helvetica', 'italic')
    doc.setFontSize(9.5)
    doc.setTextColor(71, 85, 105)
    doc.text(subtitle, 30, currentY)
    currentY += 16
  }

  // Render KPI boxes if provided
  if (kpis.length > 0) {
    const boxCount = Math.min(kpis.length, 5)
    const gap = 12
    const totalGap = gap * (boxCount - 1)
    const boxWidth = (pageWidth - 60 - totalGap) / boxCount
    const boxHeight = 44

    kpis.slice(0, boxCount).forEach((kpi, index) => {
      const x = 30 + index * (boxWidth + gap)
      doc.setFillColor(248, 250, 252) // slate-50
      doc.setDrawColor(226, 232, 240)
      doc.roundedRect(x, currentY, boxWidth, boxHeight, 4, 4, 'FD')

      doc.setFont('helvetica', 'bold')
      doc.setFontSize(7.5)
      doc.setTextColor(100, 116, 139)
      doc.text(kpi.label.toUpperCase().slice(0, 22), x + 8, currentY + 14)

      doc.setFont('helvetica', 'bold')
      doc.setFontSize(12)
      doc.setTextColor(30, 41, 59)
      doc.text(String(kpi.value), x + 8, currentY + 32)
    })

    currentY += boxHeight + 16
  }

  // Format table data
  const head = [columns.map((col) => col.header)]
  const body = rows.map((row) =>
    columns.map((col) => {
      const val = row[col.key]
      if (val === null || val === undefined) return '—'
      if (typeof val === 'number') {
        if (col.key.includes('amount') || col.key.includes('cost') || col.key.includes('price') || col.key.includes('balance') || col.key.includes('revenue') || col.key.includes('profit') || col.key.includes('total')) {
          return `₹${val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
        }
        return val.toLocaleString('en-IN')
      }
      return String(val)
    }),
  )

  if (summaryRow) {
    const sumRowValues = columns.map((col, idx) => {
      if (idx === 0) return 'Total Summary'
      const val = summaryRow[col.key]
      if (val === null || val === undefined) return ''
      if (typeof val === 'number') {
        return `₹${val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      }
      return String(val)
    })
    body.push(sumRowValues)
  }

  const columnStyles: Record<number, { halign?: 'left' | 'right' | 'center'; fontStyle?: 'bold' | 'normal' }> = {}
  columns.forEach((col, idx) => {
    if (col.align) {
      columnStyles[idx] = { halign: col.align }
    }
  })

  autoTable(doc, {
    startY: currentY,
    head,
    body,
    margin: { left: 30, right: 30, bottom: 40 },
    theme: 'grid',
    headStyles: {
      fillColor: [67, 56, 202], // indigo-700
      textColor: [255, 255, 255],
      fontSize: 8.5,
      fontStyle: 'bold',
      halign: 'left',
      cellPadding: 5,
    },
    bodyStyles: {
      fontSize: 8,
      textColor: [51, 65, 85],
      cellPadding: 4.5,
    },
    alternateRowStyles: {
      fillColor: [248, 250, 252],
    },
    columnStyles,
    didDrawPage: (data) => {
      // Footer on every page
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(8)
      doc.setTextColor(148, 163, 184)
      doc.text('Confidential & Proprietary • Shiva Prints Operational Management System', 30, pageHeight - 18)
      const pageInfo = `Page ${data.pageNumber}`
      doc.text(pageInfo, pageWidth - 30, pageHeight - 18, { align: 'right' })
    },
  })

  const dateStr = new Date().toISOString().slice(0, 10)
  const filename = `ShivaPrints_${filenamePrefix.replace(/\s+/g, '_')}_${dateStr}.pdf`
  doc.save(filename)
}
