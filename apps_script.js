/**
 * Immo-Scanner Google Apps Script
 *
 * Setup:
 * 1. Dieses Script in Google Sheet einfuegen (Erweiterungen -> Apps Script)
 * 2. Bereitstellen -> Neue Bereitstellung -> Web-App
 *    - Ausfuehren als: Ich
 *    - Zugriff: Jeder
 * 3. URL kopieren und als GitHub Secret GOOGLE_SHEETS_WEBAPP_URL speichern
 */

const SHEET_NAME = "Neue Objekte";

// Spalten-Header (Reihenfolge wie im Sheet)
const HEADERS = [
    "Status",
    "Inserat",
    "Expose",
    "Stadt",
    "Strasse",
    "Kaufpreis",
    "Zimmer",
    "Makler",
    "Notiz",
    "QM",
    "QM Preis",
    "Jahreskaltmiete",
    "Rendite",
    "Baujahr",
    "Notiz2"
];

/**
 * GET Handler - Test ob Script erreichbar
 */
function doGet(e) {
    return ContentService
        .createTextOutput(JSON.stringify({
                status: "ok",
                message: "Immo-Scanner Web-App laeuft",
                sheet: SHEET_NAME,
                timestamp: new Date().toISOString()
        }))
        .setMimeType(ContentService.MimeType.JSON);
}

/**
 * POST Handler - Empfaengt Listings vom Python-Script
 */
function doPost(e) {
    try {
        const payload = JSON.parse(e.postData.contents);
        const listings = payload.listings || [];

        if (listings.length === 0) {
            return ContentService
                .createTextOutput(JSON.stringify({ status: "ok", added: 0 }))
                .setMimeType(ContentService.MimeType.JSON);
        }

        const sheet = getOrCreateSheet();

        let added = 0;
        for (const listing of listings) {
            appendListing(sheet, listing);
            added++;
        }

        // Formatierung anwenden
        formatSheet(sheet);

        return ContentService
            .createTextOutput(JSON.stringify({
                status: "ok",
                added: added,
                timestamp: new Date().toISOString()
            }))
            .setMimeType(ContentService.MimeType.JSON);

    } catch (err) {
        return ContentService
            .createTextOutput(JSON.stringify({
                status: "error",
                message: err.toString()
            }))
            .setMimeType(ContentService.MimeType.JSON);
    }
}

/**
 * Sheet holen oder erstellen
 */
function getOrCreateSheet() {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let sheet = ss.getSheetByName(SHEET_NAME);

    if (!sheet) {
        sheet = ss.insertSheet(SHEET_NAME);

        // Header-Zeile
        const headerRange = sheet.getRange(1, 1, 1, HEADERS.length);
        headerRange.setValues([HEADERS]);
        headerRange.setBackground("#1a73e8");
        headerRange.setFontColor("#ffffff");
        headerRange.setFontWeight("bold");
        headerRange.setFontSize(10);

        // Spaltenbreiten
        sheet.setColumnWidth(1, 80);   // Status
        sheet.setColumnWidth(2, 200);  // Inserat
        sheet.setColumnWidth(3, 200);  // Expose
        sheet.setColumnWidth(4, 100);  // Stadt
        sheet.setColumnWidth(5, 150);  // Strasse
        sheet.setColumnWidth(6, 100);  // Kaufpreis
        sheet.setColumnWidth(7, 60);   // Zimmer
        sheet.setColumnWidth(8, 120);  // Makler
        sheet.setColumnWidth(9, 200);  // Notiz
        sheet.setColumnWidth(10, 60);  // QM
        sheet.setColumnWidth(11, 80);  // QM Preis
        sheet.setColumnWidth(12, 120); // Jahreskaltmiete
        sheet.setColumnWidth(13, 80);  // Rendite
        sheet.setColumnWidth(14, 80);  // Baujahr
        sheet.setColumnWidth(15, 200); // Notiz2

        // Zeile einfrieren
        sheet.setFrozenRows(1);

        Logger.log("Sheet '" + SHEET_NAME + "' erstellt");
    }

    return sheet;
}

/**
 * Listing als Zeile einfuegen
 */
function appendListing(sheet, listing) {
    const row = [
        listing.status || '',
        listing.url || '',
        listing.expose || '',
        listing.stadt || '',
        listing.strasse || '',
        listing.preis || 0,
        listing.zimmer || '',
        listing.makler || '',
        listing.notiz || '',
        listing.qm || '',
        listing.qm_preis || '',
        listing.jahreskaltmiete || '',
        listing.rendite || '',
        listing.baujahr || '',
        listing.notiz2 || ''
    ];

    sheet.appendRow(row);
}

/**
 * Tabelle formatieren
 */
function formatSheet(sheet) {
    const lastRow = sheet.getLastRow();
    if (lastRow < 2) return;

    // Abwechselnde Zeilenfarben
    for (let i = 2; i <= lastRow; i++) {
        const range = sheet.getRange(i, 1, 1, HEADERS.length);
        if (i % 2 === 0) {
            range.setBackground("#f8f9fa");
        } else {
            range.setBackground("#ffffff");
        }
    }

    // Inserat-Spalte (2) als Hyperlink formatieren
    for (let i = 2; i <= lastRow; i++) {
        const urlCell = sheet.getRange(i, 2);
        const url = urlCell.getValue();
        if (url && url.toString().startsWith('http')) {
            urlCell.setFormula('=HYPERLINK("' + url + '","Link")');
        }
    }

    // Rendite-Spalte (13) einfaerben: >5% gruen, sonst rot
    for (let i = 2; i <= lastRow; i++) {
        const renditeCell = sheet.getRange(i, 13);
        const val = renditeCell.getValue();
        const num = parseFloat(val);
        if (!isNaN(num)) {
            if (num >= 5) {
                renditeCell.setBackground("#c6efce");
            } else {
                renditeCell.setBackground("#ffc7ce");
            }
        }
    }
}
