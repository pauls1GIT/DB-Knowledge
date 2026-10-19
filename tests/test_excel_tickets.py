from io import BytesIO
import pytest
from openpyxl import load_workbook
from kedb.application.excel_tickets import ticket_template, read_ticket_workbook
from kedb.application.incidents import incidents_from_json, batch_items


def workbook_bytes(rows):
    book = load_workbook(BytesIO(ticket_template()))
    for row in rows:
        book['Tickets'].append(row)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def test_template_upload_maps_to_processing_queue():
    content = workbook_bytes([['Timeout', 'Connection failed', 'Restart'],
                              [None, None, None],
                              ['Crash', 'Service exited', 'Patch']])
    tickets = read_ticket_workbook(content)
    items = batch_items(incidents_from_json(tickets))
    assert len(items) == 2
    assert items[0]['external_key'].startswith('KEDB-')
    assert tickets == read_ticket_workbook(content)
    assert items[0]['external_key'] != items[1]['external_key']
    assert items[1]['resolution'] == 'Patch'


@pytest.mark.parametrize('rows,message', [
    ([], 'at least one'),
    ([['Timeout', 'Details', None]], 'Row 2'),
    ([['=1+1', 'Details', 'Fix']], 'formulas'),
])
def test_invalid_upload_is_rejected(rows, message):
    with pytest.raises(ValueError, match=message):
        read_ticket_workbook(workbook_bytes(rows))


def test_corrupt_workbook_has_readable_error():
    with pytest.raises(ValueError, match='valid .xlsx'):
        read_ticket_workbook(b'not an excel file')
