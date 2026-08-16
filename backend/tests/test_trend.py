import asyncio


async def main():
    from app.core.database import async_session
    from app.services.trends import snapshot_daily_trends

    try:
        async with async_session() as db:
            result = await snapshot_daily_trends(db)
            print("Result:", result)
            await db.commit()
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


asyncio.run(main())
