/**
 * AndesOrtoBOT → Google Sheet
 * Recibe cada solicitud del bot y la agrega como fila en la pestaña "Pedidos nuevos" o "Reparaciones".
 *
 * Instalación:
 *  1. Cree un Google Sheet (ej. "AndesOrto – Solicitudes") → Extensiones → Apps Script.
 *  2. Pegue este código y cambie SECRET por una clave larga (la misma que SHEETS_SECRET en el .env del bot).
 *  3. Implementar → Nueva implementación → Tipo: Aplicación web
 *       Ejecutar como: Yo  ·  Quién tiene acceso: Cualquier usuario
 *  4. Copie la URL (termina en /exec) en SHEETS_WEBHOOK_URL del .env.
 */
const SECRET = 'CAMBIAR-POR-UNA-CLAVE-LARGA';

const SHEETS = {
  nuevo: {
    name: 'Pedidos nuevos',
    columns: ['codigo', 'fecha', 'aparato', 'doctor', 'paciente', 'color', 'indicaciones', 'whatsapp', 'origen', 'estado'],
  },
  reparacion: {
    name: 'Reparaciones',
    columns: ['codigo', 'fecha', 'aparato', 'doctor', 'paciente', 'descripcion', 'whatsapp', 'origen', 'estado'],
  },
};

const HEADERS = {
  codigo: 'Código', fecha: 'Fecha', aparato: 'Aparato', doctor: 'Doctor', paciente: 'Paciente', color: 'Color',
  indicaciones: 'Indicaciones', descripcion: 'Descripción del daño', whatsapp: 'WhatsApp', origen: 'Origen',
  estado: 'Estado',
};

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const data = JSON.parse(e.postData.contents);
    if (data.secret !== SECRET) return json_({ ok: false, error: 'unauthorized' });
    const cfg = SHEETS[data.tipo];
    if (!cfg) return json_({ ok: false, error: 'tipo inválido' });

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let sheet = ss.getSheetByName(cfg.name);
    if (!sheet) {
      sheet = ss.insertSheet(cfg.name);
      sheet.appendRow(cfg.columns.map((c) => HEADERS[c]));
      sheet.getRange(1, 1, 1, cfg.columns.length).setFontWeight('bold');
      sheet.setFrozenRows(1);
    }
    data.estado = data.estado || 'Pendiente';
    // El apóstrofo evita que Sheets convierta el número de WhatsApp en notación científica
    sheet.appendRow(cfg.columns.map((c) => (c === 'whatsapp' && data[c] ? "'" + data[c] : data[c] || '')));
    return json_({ ok: true });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
