#!/bin/bash
set -e

# start_cloud.sh - Entrypoint dla FootStats w Cloud Run

echo "--- FootStats Cloud Runner ---"
echo "Zadanie: ${AGENT_TASK:-daily_agent}"

# 1. Synchronizacja bazy danych (opcjonalnie z GCS jeśli BUCKET_NAME jest ustawiony)
if [ -n "$BUCKET_NAME" ]; then
    echo "Pobieram bazę danych z gs://$BUCKET_NAME/data/footstats_backtest.db ..."
    # gcloud storage cp gs://$BUCKET_NAME/data/footstats_backtest.db ./data/
fi

# 2. Wybór agenta do uruchomienia
case "$AGENT_TASK" in
    "daily")
        python -m footstats.daily_agent --faza final
        ;;
    "evening")
        python -m footstats.evening_agent
        ;;
    "lineup_check")
        # Specjalna faza do sprawdzania składów 30 min przed meczem
        python -m footstats.daily_agent --faza final --tylko-kupon
        ;;
    *)
        # Domyślnie uruchom daily agent
        python -m footstats.daily_agent "$@"
        ;;
esac

# 3. Synchronizacja powrotna bazy danych
if [ -n "$BUCKET_NAME" ]; then
    echo "Wysyłam zaktualizowaną bazę do gs://$BUCKET_NAME/data/footstats_backtest.db ..."
    # gcloud storage cp ./data/footstats_backtest.db gs://$BUCKET_NAME/data/
fi

echo "--- Zadanie ukończone ---"
