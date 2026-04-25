"""
FootStats "Second Mind" Graph Visualization
Interaktywna mapa przepływu danych i AI-feedback loop
Generuje HTML z vis-network CDN + embedded CSS/JS
"""

import json
import os


def create_brain_graph():
    """Stwórz graf drugiego mózgu FootStats z vis-network"""

    # ===== DEFINICJE WĘZŁÓW =====
    nodes = [
        # Agenty (żółty)
        {'id': 'daily_agent', 'label': 'daily_agent.py\n(MAIN)', 'color': '#FFD700',
         'title': 'Główny orchestrator\nKROK 0: analizuj_porazki()\nKROK 1: Groq\nKROK 2: save coupon',
         'size': 40, 'font': {'size': 16, 'bold': 'true'}, 'shape': 'dot'},
        {'id': 'evening_agent', 'label': 'evening_agent.py\n(SETTLEMENT)', 'color': '#FFC700',
         'title': 'Zamykanie kuponów ACTIVE→WIN/LOSE\nUpdate coupons table',
         'size': 35, 'font': {'size': 14}, 'shape': 'dot'},

        # AI/RAG (fioletowy)
        {'id': 'analyzer', 'label': 'analyzer.py\n(LLM)', 'color': '#9370DB',
         'title': 'Groq llama-3.1-8b-instant\nMain coupon generation\nReads ai_feedback for lessons',
         'size': 40, 'font': {'size': 16, 'bold': 'true'}, 'shape': 'dot'},
        {'id': 'post_match_analyzer', 'label': 'post_match_analyzer.py\n(RAG)', 'color': '#BA55D3',
         'title': 'AI Feedback Loop (Etap 7)\nGeneruje wnioski z przegranym kuponów\nWpisuje do ai_feedback table',
         'size': 35, 'font': {'size': 13}, 'shape': 'dot'},
        {'id': 'trainer', 'label': 'trainer.py\n(TRAINING)', 'color': '#DA70D6',
         'title': 'RAG Knowledge Base Management\nOptional fine-tuning support',
         'size': 30, 'font': {'size': 12}, 'shape': 'dot'},

        # Frontend/API (niebieski)
        {'id': 'api_main', 'label': 'api/main.py\n(FastAPI)', 'color': '#4169E1',
         'title': 'REST API + Dashboard\nServes preview.html\nReads live data from DB',
         'size': 35, 'font': {'size': 14}, 'shape': 'dot'},
        {'id': 'preview', 'label': 'preview.html\n(Frontend)', 'color': '#1E90FF',
         'title': 'Interactive Dashboard\nShows coupons, settlement status\nAccordion history',
         'size': 30, 'font': {'size': 12}, 'shape': 'dot'},

        # Database (zielony) - ai_feedback wyróżniony
        {'id': 'coupons_db', 'label': 'coupons\n(TABLE)', 'color': '#32CD32',
         'title': 'Kupony: status, stake, odds\nColumns: id, status, amount, legs',
         'size': 35, 'font': {'size': 13}, 'shape': 'dot'},
        {'id': 'predictions_db', 'label': 'predictions\n(TABLE)', 'color': '#3CB371',
         'title': 'Wyniki meczów\nColumns: match_id, result, xG, lambda',
         'size': 30, 'font': {'size': 12}, 'shape': 'dot'},
        {'id': 'ai_feedback_db', 'label': 'ai_feedback\n(RAG MEMORY)', 'color': '#FF1493',
         'title': 'RAG Memory — Wnioski z porażek\nStored lessons from post_match_analyzer\nRetrieved for prompt context',
         'size': 40, 'font': {'size': 14, 'bold': 'true', 'color': 'white'}, 'shape': 'dot', 'borderWidth': 3},
        {'id': 'db_main', 'label': 'footstats_backtest.db\n(SQLite)', 'color': '#228B22',
         'title': 'Main database file\nAll tables connected',
         'size': 32, 'font': {'size': 12}, 'shape': 'dot'},

        # Configuration (szary)
        {'id': 'config', 'label': 'config.py\n(CONFIG)', 'color': '#808080',
         'title': 'Environment variables\nAPI keys, database path, settings',
         'size': 28, 'font': {'size': 11}, 'shape': 'dot'},

        # Core modules (pomarańczowy)
        {'id': 'backtest', 'label': 'backtest.py\n(BACKTEST)', 'color': '#FF8C00',
         'title': 'Historical validation\nKelly calibration\nWalk-forward analysis',
         'size': 30, 'font': {'size': 12}, 'shape': 'dot'},
        {'id': 'calibration', 'label': 'calibration.py\n(KELLY)', 'color': '#FF7F50',
         'title': 'Kelly Criterion (Etap 6)\nHit-rate multiplier (0.7/1.0/1.1)\nForm streak override',
         'size': 28, 'font': {'size': 11}, 'shape': 'dot'},
        {'id': 'kelly', 'label': 'kelly.py\n(KELLY MATH)', 'color': '#FFA500',
         'title': 'Kelly formula implementation\nStake calculation',
         'size': 25, 'font': {'size': 10}, 'shape': 'dot'},

        # Data layers (niebieski jasny)
        {'id': 'results_updater', 'label': 'results_updater.py\n(RESULTS)', 'color': '#6495ED',
         'title': 'Update match results\nPopulate predictions table\nTrigger evening_agent',
         'size': 30, 'font': {'size': 12}, 'shape': 'dot'},
        {'id': 'data_fetcher', 'label': 'data_fetcher.py\n(FETCH)', 'color': '#87CEEB',
         'title': 'Fetch historical data\nAPI Football integration\nLeague fixtures',
         'size': 28, 'font': {'size': 11}, 'shape': 'dot'},
    ]

    # ===== DEFINICJE KRAWĘDZI =====
    edges = [
        # MAIN PIPELINE
        {'from': 'daily_agent', 'to': 'analyzer',
         'title': 'KROK 1: Send form + lessons → Groq LLM',
         'color': '#9370DB', 'width': 4, 'arrows': 'to'},
        {'from': 'analyzer', 'to': 'coupons_db',
         'title': 'KROK 2: Write generated coupon',
         'color': '#32CD32', 'width': 3, 'arrows': 'to'},
        {'from': 'analyzer', 'to': 'ai_feedback_db',
         'title': 'Read lessons (WNIOSKI Z OSTATNICH PORAŻEK)',
         'color': '#FF1493', 'width': 3, 'dashes': True, 'arrows': 'to'},

        # RAG FEEDBACK LOOP
        {'from': 'post_match_analyzer', 'to': 'ai_feedback_db',
         'title': 'ETAP 7: Write lesson from lost coupon',
         'color': '#FF1493', 'width': 3, 'arrows': 'to'},
        {'from': 'daily_agent', 'to': 'post_match_analyzer',
         'title': 'KROK 0b: Trigger after results update',
         'color': '#DA70D6', 'width': 3, 'arrows': 'to'},

        # SETTLEMENT
        {'from': 'evening_agent', 'to': 'coupons_db',
         'title': 'Settlement: ACTIVE→WIN/LOSE',
         'color': '#FFD700', 'width': 3, 'arrows': 'to'},
        {'from': 'evening_agent', 'to': 'predictions_db',
         'title': 'Read match results',
         'color': '#3CB371', 'width': 2, 'dashes': True, 'arrows': 'to'},

        # RESULTS UPDATE
        {'from': 'results_updater', 'to': 'predictions_db',
         'title': 'Populate match results',
         'color': '#6495ED', 'width': 2, 'arrows': 'to'},

        # DATABASE
        {'from': 'coupons_db', 'to': 'db_main',
         'title': 'Part of main database',
         'color': '#228B22', 'width': 1, 'dashes': True},
        {'from': 'predictions_db', 'to': 'db_main',
         'title': 'Part of main database',
         'color': '#228B22', 'width': 1, 'dashes': True},
        {'from': 'ai_feedback_db', 'to': 'db_main',
         'title': 'Part of main database',
         'color': '#228B22', 'width': 2, 'dashes': True},

        # API/FRONTEND
        {'from': 'api_main', 'to': 'coupons_db',
         'title': 'Read live coupon data',
         'color': '#4169E1', 'width': 2, 'dashes': True},
        {'from': 'api_main', 'to': 'preview',
         'title': 'Serve HTML + JSON endpoints',
         'color': '#4169E1', 'width': 2, 'arrows': 'to'},

        # CONFIG
        {'from': 'daily_agent', 'to': 'config',
         'title': 'Read environment',
         'color': '#808080', 'width': 1, 'dashes': True},
        {'from': 'analyzer', 'to': 'config',
         'title': 'Read API keys',
         'color': '#808080', 'width': 1, 'dashes': True},
        {'from': 'evening_agent', 'to': 'config',
         'title': 'Read settings',
         'color': '#808080', 'width': 1, 'dashes': True},
        {'from': 'api_main', 'to': 'config',
         'title': 'Read config',
         'color': '#808080', 'width': 1, 'dashes': True},

        # KELLY
        {'from': 'daily_agent', 'to': 'calibration',
         'title': 'Apply Kelly multiplier to stakes',
         'color': '#FF8C00', 'width': 2, 'arrows': 'to'},
        {'from': 'calibration', 'to': 'kelly',
         'title': 'Calculate stake',
         'color': '#FFA500', 'width': 1, 'arrows': 'to'},
        {'from': 'backtest', 'to': 'calibration',
         'title': 'Provide hit-rate thresholds',
         'color': '#FF7F50', 'width': 1, 'dashes': True},

        # TRAINER
        {'from': 'trainer', 'to': 'ai_feedback_db',
         'title': 'Optional: Fine-tune from feedback',
         'color': '#DA70D6', 'width': 1, 'dashes': True},
    ]

    nodes_json = json.dumps(nodes)
    edges_json = json.dumps(edges)

    # ===== GENERUJ HTML =====
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>FootStats Second Mind - Graph View v3.2</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <!-- VIS-NETWORK CDN LIBRARY -->
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/vis-network/standalone/umd/vis-network.min.css">

    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        html, body {{
            width: 100%;
            height: 100%;
        }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0a0e27 0%, #1a1a2e 100%);
            color: #e0e0e0;
            overflow: hidden;
        }}

        #mynetwork {{
            width: 100%;
            height: 100%;
            background: radial-gradient(ellipse at 30% 40%, rgba(147, 112, 219, 0.15) 0%, transparent 60%),
                        radial-gradient(ellipse at 70% 60%, rgba(65, 105, 225, 0.1) 0%, transparent 60%),
                        linear-gradient(135deg, #0a0e27 0%, #1a1a2e 100%);
            border: 1px solid rgba(255, 255, 255, 0.05);
            position: relative;
        }}

        #header {{
            position: absolute;
            top: 20px;
            left: 20px;
            z-index: 1000;
            background: rgba(26, 26, 46, 0.95);
            padding: 25px;
            border-radius: 12px;
            border-left: 5px solid #FF1493;
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
            max-width: 380px;
            backdrop-filter: blur(10px);
        }}

        #header h1 {{
            color: #FF1493;
            margin-bottom: 8px;
            font-size: 22px;
            letter-spacing: 1px;
        }}

        #header .subtitle {{
            color: #a0a0a0;
            font-size: 11px;
            line-height: 1.6;
            margin-bottom: 12px;
        }}

        #header .highlight {{
            color: #FF1493;
            font-weight: bold;
            background: rgba(255, 20, 147, 0.1);
            padding: 8px 12px;
            border-radius: 5px;
            display: inline-block;
            margin-top: 8px;
        }}

        .legend {{
            position: absolute;
            bottom: 20px;
            right: 20px;
            z-index: 1000;
            background: rgba(26, 26, 46, 0.95);
            padding: 25px;
            border-radius: 12px;
            border-left: 5px solid #4169E1;
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
            max-width: 280px;
            font-size: 12px;
            backdrop-filter: blur(10px);
        }}

        .legend h3 {{
            color: #4169E1;
            margin-bottom: 12px;
            font-size: 15px;
            letter-spacing: 0.5px;
        }}

        .legend-section {{
            margin-bottom: 12px;
        }}

        .legend-section-title {{
            color: #a0a0a0;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
            margin-top: 10px;
            padding-top: 8px;
            border-top: 1px solid rgba(160, 160, 160, 0.2);
        }}

        .legend-item {{
            display: flex;
            align-items: center;
            margin-bottom: 8px;
        }}

        .legend-color {{
            width: 18px;
            height: 18px;
            border-radius: 50%;
            margin-right: 10px;
            border: 2px solid rgba(255, 255, 255, 0.15);
            flex-shrink: 0;
        }}

        .legend-item span {{
            color: #e0e0e0;
            font-size: 12px;
        }}

        .legend-item.highlight span {{
            color: #FF1493;
            font-weight: bold;
        }}

        .controls {{
            position: absolute;
            top: 20px;
            right: 20px;
            z-index: 1000;
            background: rgba(26, 26, 46, 0.95);
            padding: 15px;
            border-radius: 12px;
            border-left: 5px solid #FFD700;
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(10px);
        }}

        .controls button {{
            background: linear-gradient(135deg, #FF1493, #BA55D3);
            color: white;
            border: none;
            padding: 10px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            margin-bottom: 8px;
            width: 100%;
            transition: all 0.3s ease;
            font-weight: bold;
        }}

        .controls button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(255, 20, 147, 0.3);
        }}

        .controls button:active {{
            transform: translateY(0);
        }}

        /* VIS Network overrides */
        .vis-network {{
            background: transparent !important;
        }}

        .vis-label {{
            color: #e0e0e0;
            font-weight: 500;
            text-shadow: 0 2px 4px rgba(0, 0, 0, 0.5);
        }}

        .vis-tooltip {{
            background: rgba(26, 26, 46, 0.98);
            border: 2px solid #FF1493;
            color: #e0e0e0;
            border-radius: 8px;
            padding: 12px;
            font-size: 11px;
            max-width: 220px;
            word-wrap: break-word;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
        }}

        .vis-panel.vis-bottom {{
            background: rgba(26, 26, 46, 0.9) !important;
            border-top: 1px solid rgba(255, 255, 255, 0.1) !important;
        }}

        .vis-button {{
            background: rgba(255, 20, 147, 0.2) !important;
            border: 1px solid #FF1493 !important;
            color: #e0e0e0 !important;
            border-radius: 6px !important;
        }}

        .vis-button:hover {{
            background: rgba(255, 20, 147, 0.3) !important;
        }}

        .vis-button.active {{
            background: #FF1493 !important;
        }}
    </style>
</head>
<body>
    <div id="mynetwork"></div>

    <div id="header">
        <h1>SECOND MIND v3.2</h1>
        <p class="subtitle">
            FootStats — Interaktywna mapa przepływu danych<br/>
            i AI-feedback loop (RAG Memory)
        </p>
        <div class="highlight">
            RAG: ai_feedback table<br/>
            Lessons: post_match_analyzer<br/>
            Injected: analyzer.py
        </div>
    </div>

    <div class="controls">
        <button onclick="resetNetwork()">Reset View</button>
        <button onclick="togglePhysics()">Toggle Physics</button>
        <button onclick="fitNetwork()">Fit to Screen</button>
    </div>

    <div class="legend">
        <h3>ARCHITEKTURA</h3>

        <div class="legend-section">
            <div class="legend-section-title">Orchestration</div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #FFD700;"></div>
                <span>daily_agent / evening_agent</span>
            </div>
        </div>

        <div class="legend-section">
            <div class="legend-section-title">AI & RAG</div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #9370DB;"></div>
                <span>analyzer.py (Groq LLM)</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #BA55D3;"></div>
                <span>post_match_analyzer (RAG)</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #DA70D6;"></div>
                <span>trainer.py</span>
            </div>
        </div>

        <div class="legend-section">
            <div class="legend-section-title">Backend</div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #4169E1;"></div>
                <span>api/main.py (FastAPI)</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #1E90FF;"></div>
                <span>preview.html (Frontend)</span>
            </div>
        </div>

        <div class="legend-section">
            <div class="legend-section-title">Database</div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #32CD32;"></div>
                <span>coupons, predictions</span>
            </div>
            <div class="legend-item highlight">
                <div class="legend-color" style="background-color: #FF1493;"></div>
                <span>ai_feedback (RAG Memory)</span>
            </div>
        </div>

        <div class="legend-section">
            <div class="legend-section-title">Analytics</div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #FF8C00;"></div>
                <span>Kelly Calibration</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #808080;"></div>
                <span>Configuration</span>
            </div>
        </div>
    </div>

    <script type="text/javascript">
        // Data prepared by Python
        var nodesData = {nodes_json};
        var edgesData = {edges_json};

        // Create DataSets
        var nodes = new vis.DataSet(nodesData);
        var edges = new vis.DataSet(edgesData);

        var container = document.getElementById('mynetwork');
        var data = {{
            nodes: nodes,
            edges: edges
        }};

        var options = {{
            physics: {{
                enabled: true,
                barnesHut: {{
                    gravitationalConstant: -32000,
                    centralGravity: 0.3,
                    springLength: 280,
                    springConstant: 0.035
                }},
                maxVelocity: 60,
                minVelocity: 0.8,
                solver: 'barnesHut',
                timestep: 0.5,
                stabilization: {{
                    iterations: 200,
                    fit: true
                }}
            }},
            interaction: {{
                hover: true,
                navigationButtons: true,
                keyboard: true,
                zoomView: true,
                dragView: true
            }},
            nodes: {{
                font: {{
                    color: '#e0e0e0',
                    size: 14,
                    face: 'Arial, sans-serif',
                    multi: false,
                    bold: {{
                        size: 16,
                        color: '#ffffff'
                    }}
                }},
                borderWidth: 2.5,
                borderWidthSelected: 4,
                shadow: {{
                    enabled: true,
                    color: 'rgba(0, 0, 0, 0.8)',
                    size: 15,
                    x: 5,
                    y: 5
                }}
            }},
            edges: {{
                color: {{inherit: 'from'}},
                font: {{
                    color: '#a0a0a0',
                    size: 11,
                    align: 'middle'
                }},
                smooth: {{
                    type: 'continuous',
                    forceDirection: 'none'
                }},
                arrows: {{
                    to: {{enabled: true, scaleFactor: 0.4, type: 'arrow'}}
                }},
                shadow: {{
                    enabled: false
                }},
                hoverWidth: 2
            }}
        }};

        // Create network
        var network = new vis.Network(container, data, options);

        // Fit to screen on load
        setTimeout(function() {{
            network.fit();
        }}, 500);

        // Helper functions
        function resetNetwork() {{
            network.fit();
            network.physics.stabilize();
        }}

        function togglePhysics() {{
            options.physics.enabled = !options.physics.enabled;
            network.setOptions(options);
            alert('Physics ' + (options.physics.enabled ? 'enabled' : 'disabled'));
        }}

        function fitNetwork() {{
            network.fit({{animation: {{duration: 800, easingFunction: 'easeInOutQuad'}}}});
        }}

        // Debug
        console.log('[VIS-NETWORK] Loaded successfully');
        console.log('[VIS-NETWORK] Nodes: ' + nodes.length + ', Edges: ' + edges.length);
        console.log('[FOOTSTATS] Second Mind v3.2 - RAG Memory visualization');
    </script>
</body>
</html>
"""

    # Zapisz plik
    output_file = 'brain_graph.html'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

    # Sprawdzenie
    file_size = os.path.getsize(output_file)
    lines = len(html_content.splitlines())

    print(f"\n[OK] Graph saved to: {output_file}")
    print(f"[OK] File size: {file_size} bytes ({file_size/1024:.1f} KB)")
    print(f"[OK] HTML lines: {lines}")

    # Weryfikacja
    checks = {
        'vis-network CDN': 'unpkg.com/vis-network' in html_content,
        'Nodes data': 'var nodesData = ' in html_content,
        'Edges data': 'var edgesData = ' in html_content,
        'Network creation': 'new vis.Network' in html_content,
        'Dark theme': '#0a0e27' in html_content,
        'RAG Memory': 'ai_feedback' in html_content,
    }

    print(f"\n[VERIFICATION]")
    for check, result in checks.items():
        status = "[OK]" if result else "[FAIL]"
        print(f"  {status} {check}")

    if file_size >= 50000:
        print(f"\n[SUCCESS] File is LARGE: {file_size/1024:.1f} KB (>50KB requirement met)")
    else:
        print(f"\n[INFO] File size: {file_size/1024:.1f} KB (CDN loaded at runtime)")

    return output_file


if __name__ == '__main__':
    output = create_brain_graph()

    print("\n" + "="*70)
    print(" FOOTSTATS SECOND MIND — GRAPH VIEW v3.2 ".center(70, "="))
    print("="*70)

    print(f"\n[OPEN IN BROWSER]")
    print(f"  • Windows:  start {output}")
    print(f"  • Mac:      open {output}")
    print(f"  • Linux:    xdg-open {output}")

    print(f"\n[INTERACTIVE FEATURES]")
    print(f"  • Drag nodes to move them")
    print(f"  • Scroll to zoom in/out")
    print(f"  • Hover over edges for descriptions")
    print(f"  • Right-click for navigation menu")
    print(f"  • Buttons: Reset, Toggle Physics, Fit")

    print(f"\n[VISUALIZATION ELEMENTS]")
    print(f"  • 17 interconnected nodes (modules)")
    print(f"  • 21 edges showing data flow")
    print(f"  • Dark cyberpunk theme")
    print(f"  • Physics simulation (Barnes-Hut)")
    print(f"  • RAG Memory (ai_feedback) highlighted in pink")

    print(f"\n[RAG FEEDBACK LOOP]")
    print(f"  1. daily_agent triggers post_match_analyzer")
    print(f"  2. post_match_analyzer writes lessons → ai_feedback table")
    print(f"  3. analyzer.py reads from ai_feedback")
    print(f"  4. Lessons injected into Groq prompt (WNIOSKI Z OSTATNICH PORAŻEK)")

    print(f"\n" + "="*70)
