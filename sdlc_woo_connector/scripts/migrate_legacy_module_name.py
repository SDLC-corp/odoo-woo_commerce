import argparse
import sys

import psycopg2


LEGACY_MODULE = "woo_connector"
CANONICAL_MODULE = "sdlc_woo_connector"


def fetch_one(cur, query, params=()):
    cur.execute(query, params)
    return cur.fetchone()


def migrate(connection):
    cur = connection.cursor()

    legacy_row = fetch_one(
        cur,
        """
        SELECT id, name, state, latest_version
          FROM ir_module_module
         WHERE name = %s
        """,
        (LEGACY_MODULE,),
    )
    canonical_row = fetch_one(
        cur,
        """
        SELECT id, name, state, latest_version
          FROM ir_module_module
         WHERE name = %s
        """,
        (CANONICAL_MODULE,),
    )

    print("LEGACY_ROW", legacy_row)
    print("CANONICAL_ROW", canonical_row)

    if not legacy_row:
        print("No legacy module row found. Nothing to migrate.")
        return

    legacy_id, _legacy_name, legacy_state, legacy_version = legacy_row
    if canonical_row and canonical_row[0] == legacy_id:
        print("Module row is already canonical. Nothing to migrate.")
        return

    if canonical_row:
        canonical_id, _canonical_name, canonical_state, _canonical_version = canonical_row
        if canonical_state not in {"uninstalled", "uninstallable"}:
            raise RuntimeError(
                "Canonical module row already exists in state %s. "
                "Refusing automatic merge." % canonical_state
            )
        cur.execute("DELETE FROM ir_module_module WHERE id = %s", (canonical_id,))
        print("Deleted placeholder canonical row", canonical_id)

    cur.execute(
        """
        UPDATE ir_module_module
           SET name = %s,
               latest_version = COALESCE(latest_version, %s)
         WHERE id = %s
        """,
        (CANONICAL_MODULE, legacy_version, legacy_id),
    )
    print("Renamed module row", legacy_id, "to", CANONICAL_MODULE)

    cur.execute(
        """
        UPDATE ir_model_data legacy
           SET module = %s
         WHERE legacy.module = %s
        """,
        (CANONICAL_MODULE, LEGACY_MODULE),
    )
    print("Moved ir_model_data rows", cur.rowcount)

    cur.execute(
        """
        UPDATE ir_module_module_dependency
           SET name = %s
         WHERE name = %s
        """,
        (CANONICAL_MODULE, LEGACY_MODULE),
    )
    print("Updated dependency rows", cur.rowcount)

    cur.close()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Odoo module metadata from woo_connector to sdlc_woo_connector."
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--db", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag the script only validates connectivity.",
    )
    args = parser.parse_args()

    connection = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.db,
        user=args.user,
        password=args.password,
    )
    try:
        if not args.apply:
            print("Connected. Re-run with --apply to execute the migration.")
            return
        migrate(connection)
        connection.commit()
        print("Migration committed.")
    except Exception as exc:
        connection.rollback()
        print("Migration rolled back:", exc)
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
