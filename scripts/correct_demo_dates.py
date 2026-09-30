"""One-time correction of the untouched generated order 11; back up SQLite before use."""
from app.config import Settings
from app.database import add_history, connect, now


def correct(path):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM orders WHERE id=11').fetchone()
        if not row or (row['order_number'],row['stage'],row['promised_date_initial'],row['forecast_date'],row['completed_date']) != (
                'КФ-2611','Завершён','2026-10-10','2026-10-10','2026-10-09'):
            return False
        if db.execute("SELECT COUNT(*) FROM history WHERE order_id=11 AND event_type!='seed'").fetchone()[0]:
            raise RuntimeError('Order 11 has business history; automatic demo correction is not applicable')
        db.execute("""UPDATE orders SET promised_date_initial='2026-09-29',forecast_date='2026-09-29',
                      completed_date='2026-09-28',next_action_due='2026-09-29',updated_at=? WHERE id=11""",(now(),))
        add_history(db,11,'demo_dates_corrected',
                    'Исправлена ошибка учебного seed: завершённый заказ был датирован после DEMO_DATE. '
                    'Учебный срок: 29.09.2026, завершение: 28.09.2026. Это исправление демонстрационных данных, не перенос заказа.')
        return True


if __name__=='__main__':
    print('Demo order 11 corrected' if correct(Settings.from_env().database_path) else 'No correction needed')
