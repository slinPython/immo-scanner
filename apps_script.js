/**
 * Immo-Scanner Google Apps Script
 *
 * Setup:
 * 1. Dieses Script in Google Sheet einfuegen (Erweiterungen > Apps Script)
 * 2. Bereitstellen -> Neue Bereitstellung -> Web-App
 *    - Ausfuehren als: Ich
 *    - Zugriff: Jeder
 * 3. URL kopieren und als GitHub Secret GOOGLE_SHEETS_WEBAPP_URL setzen
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
 * GET Handler - Liefert Sheet-Daten als JSON fuer die PWA
 */
function doGet(e) {
  var action = (e && e.parameter && e.parameter.action) ? e.parameter.action : 'status';

  if (action === 'list') {
    return getListingsAsJson();
  }

  return ContentService
    .createTextOutput(JSON.stringify({
      status: "ok",
      message: "Immo-Scanner Web-App aktiv",
      sheet: SHEET_NAME,
      timestamp: new Date().toISOString()
    }))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Liest alle Listings aus dem Sheet und gibt sie als JSON zurueck
 */
function getListingsAsJson() {
  var sheet = getOrCreateSheet();
  var data = sheet.getDataRange().getValues();

  if (data.length <= 1) {
    return ContentService
      .createTextOutput(JSON.stringify({ listings: [], count: 0 }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  var headers = data[0];
  var listings = [];

  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    var obj = {};
    for (var j = 0; j < headers.length; j++) {
      var key = headers[j].toString().toLowerCase().replace(/\s+/g, '_');
      obj[key] = row[j];
    }
    // Map to PWA expected fields
    obj.platform = obj.inserat || '';
    obj.title = obj.expose || '';
    obj.price = parseFloat(obj.kaufpreis) || 0;
    obj.rooms = parseFloat(obj.zimmer) || 0;
    obj.sqm = parseFloat(obj.qm) || 0;
    obj.address = (obj.strasse || '') + (obj.stadt ? ', ' + obj.stadt : '');
    obj.rendite_normal = parseFloat((obj.rendite || '').replace('%','')) || 0;
    obj.score = obj.score || 0;
    obj.found_date = obj.datum || new Date().toISOString();
    listings.push(obj);
  }

  return ContentService
    .createTextOutput(JSON.stringify({
      listings: listings,
      count: listings.length,
      timestamp: new Date().toISOString()
    }))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * POST Handler - Empfaengt Listings vom Scanner
 */
function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents);
    const listings = payload.listings;

    if (listings.length === 0) {
      return ContentService
        .createTextOutput(JSON.stringify({status: "ok", added: 0}))
        .setMimeType(ContentService.MimeType.JSON);
    }

    const sheet = getOrCreateSheet();

    let added = 0;
    for (const listing of listings) {
      const isDuplicate = checkDuplicate(sheet, listing.url);
      if (!isDuplicate) {
        const row = HEADERS.map(h => {
          const key = h.toLowerCase().replace(/\s+/g, '_');
          if (key === 'status') return listing.status || '';
          if (key === 'inserat') return listing.url || '';
          if (key === 'expose') return listing.expose || '';
          if (key === 'stadt') return listing.stadt || '';
          if (key === 'strasse') return listing.strasse || '';
          if (key === 'kaufpreis') return listing.preis || '';
          if (key === 'zimmer') return listing.zimmer || '';
          if (key === 'makler') return listing.makler || '';
          if (key === 'notiz') return listing.notiz || '';
          if (key === 'qm') return listing.qm || '';
          if (key === 'qm_preis') return listing.qm_preis || '';
          if (key === 'jahreskaltmiete') return listing.jahreskaltmiete || '';
          if (key === 'rendite') return listing.rendite || '';
          if (key === 'baujahr') return listing.baujahr || '';
          if (key === 'notiz2') return listing.notiz2 || '';
          return '';
        });
        sheet.appendRow(row);
        added++;
      }
    }

    // Farbcodierung anwenden
    applyConditionalFormatting(sheet);

    return ContentService
      .createTextOutput(JSON.stringify({
        status: "ok",
        added: added,
        total: sheet.getLastRow() - 1
      }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (error) {
    return ContentService
      .createTextOutput(JSON.stringify({
        status: "error",
        message: error.toString()
      }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function getOrCreateSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);

  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(HEADERS);
    const headerRange = sheet.getRange(1, 1, 1, HEADERS.length);
    headerRange.setFontWeight("bold");
    headerRange.setBackground("#1a1a2e");
    headerRange.setFontColor("#ffffff");
    sheet.setFrozenRows(1);
  }

  return sheet;
}

function checkDuplicate(sheet, url) {
  if (!url) return false;
  const data = sheet.getDataRange().getValues();
  const urlCol = HEADERS.indexOf("Inserat");
  for (let i = 1; i < data.length; i++) {
    if (data[i][urlCol] === url) return true;
  }
  return false;
}

function applyConditionalFormatting(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow <= 1) return;

  const renditeCol = HEADERS.indexOf("Rendite") + 1;
  if (renditeCol <= 0) return;

  const range = sheet.getRange(2, renditeCol, lastRow - 1, 1);
  const values = range.getValues();

  for (let i = 0; i < values.length; i++) {
    const rendite = parseFloat((values[i][0] || '').toString().replace('%', ''));
    const row = i + 2;
    const rowRange = sheet.getRange(row, 1, 1, HEADERS.length);

    if (rendite >= 6) {
      rowRange.setBackground("#e6ffe6");
    } else if (rendite >= 5) {
      rowRange.setBackground("#fff9e6");
    } else {
      rowRange.setBackground("#ffe6e6");
    }
  }
}
