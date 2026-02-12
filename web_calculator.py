from flask import Flask, render_template, request, jsonify
from calculator import RecipeParser, ProductionCalculator
import os

app = Flask(__name__)

# Check if running in production (snapshot mode) or local dev (source file mode)
SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), 'recipes_snapshot.json')
try:
  from config import GAME_DATA_PATH
  base_path = GAME_DATA_PATH
  ALLOW_RELOAD = True
except ImportError:
  base_path = None
  ALLOW_RELOAD = False

if os.path.exists(SNAPSHOT_PATH):
  print("Loading from snapshot (production mode)")
  parser = RecipeParser.from_snapshot(SNAPSHOT_PATH)
  snapshot_timestamp = getattr(parser, 'snapshot_timestamp', 'Unknown')
else:
  snapshot_timestamp = 'Development Mode'
  if base_path and os.path.exists(base_path):
    print("Loading from source files (development mode)")
    parser = RecipeParser(base_path)
  else:
    raise RuntimeError("Neither snapshot file nor valid config.py found.")
calculator = ProductionCalculator(parser.recipes)
calculator.set_display_names(parser.display_name_map)

def build_graph_view(root_node):
  """Build aggregated graph view like Satisfactory calculator"""
  nodes = {}
  edges = []
  def traverse(node, parent_key=None):
    if node.recipe:
      for output_resource, output_amount in node.recipe.outputs.items():
        key = f"{node.building_type}:{node.recipe.id}"
        if key not in nodes:
          nodes[key] = {
            'type': 'production',
            'building': node.building_type,
            'recipe': node.recipe.display_name,
            'output_resource': calculator.get_display_name(output_resource),
            'output_rate': 0,
            'building_count': 0,
            'inputs': {},
            'outputs': {}
          }
        nodes[key]['building_count'] += node.building_count
        nodes[key]['output_rate'] += node.quantity_per_minute
        for input_resource, input_amount in node.recipe.inputs.items():
          input_rate = (input_amount / output_amount) * node.quantity_per_minute
          input_display = calculator.get_display_name(input_resource)
          nodes[key]['inputs'][input_display] = nodes[key]['inputs'].get(input_display, 0) + input_rate
        output_display = calculator.get_display_name(output_resource)
        nodes[key]['outputs'][output_display] = nodes[key]['outputs'].get(output_display, 0) + node.quantity_per_minute
        if parent_key:
          edges.append({'from': key, 'to': parent_key, 'resource': output_display, 'rate': node.quantity_per_minute})
        for child in node.children:
          traverse(child, key)
    else:
      key = f"raw:{node.resource}"
      if key not in nodes:
        nodes[key] = {
          'type': 'raw',
          'resource': calculator.get_display_name(node.resource),
          'rate': 0
        }
      nodes[key]['rate'] += node.quantity_per_minute
      if parent_key:
        edges.append({'from': key, 'to': parent_key, 'resource': calculator.get_display_name(node.resource), 'rate': node.quantity_per_minute})
  traverse(root_node)
  edge_map = {}
  for edge in edges:
    edge_key = (edge['from'], edge['to'])
    if edge_key not in edge_map:
      edge_map[edge_key] = {'from': edge['from'], 'to': edge['to'], 'resource': edge['resource'], 'rate': 0}
    edge_map[edge_key]['rate'] += edge['rate']
  return {'nodes': nodes, 'edges': list(edge_map.values())}

@app.route('/')
def index():
	resources = calculator.get_resource_list()
	if not ALLOW_RELOAD:  # Production mode - filter to Act I only
		resources = [r for r in resources if r != 'NONE' and r not in calculator.BASE_RESOURCES and any(recipe.phase <= 1 and recipe.building_type != 'Crusher' for recipe in calculator.recipes_by_output.get(r, []))]
	else:  # Local dev mode - show all
		resources = [r for r in resources if r != 'NONE' and r not in calculator.BASE_RESOURCES]
	resource_display = [(res, calculator.get_display_name(res)) for res in resources]
	return render_template('index.html', resources=resource_display, allow_reload=ALLOW_RELOAD, snapshot_timestamp=snapshot_timestamp)


@app.route('/calculate', methods=['POST'])
def calculate():
  data = request.json
  target_resource = data.get('resource', '').upper()
  quantity = float(data.get('quantity', 1.0))
  max_phase = int(data.get('phase', 1))
  allow_alternate = data.get('allow_alternate', True)
  allowed_alternates = data.get('allowed_alternates', None)
  chain = calculator.calculate_production_chain(target_resource, quantity, max_phase, allow_alternate, allowed_alternates)
  totals = calculator.get_total_requirements(chain)
  # Check for missing recipes
  warning = None
  if chain.building_type == "NO RECIPE":
    display_name = calculator.get_display_name(target_resource)
    warning = f"{display_name} has no recipe available in Act {max_phase}. Try selecting a higher Act."

  def serialize_node(node):
    return {
      'resource': node.resource,
      'quantity_per_minute': round(node.quantity_per_minute, 2),
      'building_type': node.building_type,
      'building_count': round(node.building_count, 2),
      'recipe_name': node.recipe.display_name if node.recipe else None,
      'recipe_inputs': node.recipe.inputs if node.recipe else {},
      'recipe_outputs': node.recipe.outputs if node.recipe else {},
      'depth': node.depth,
      'children': [serialize_node(child) for child in node.children]
    }

  graph = build_graph_view(chain)
  return jsonify({
    'chain': serialize_node(chain),
    'raw_resources': totals['raw_resources'],
    'buildings': totals['buildings'],
    'alternate_recipes': totals['alternate_recipes'],
    'graph': graph,
    'warning': warning
  })

@app.route('/get_alternate_recipes')
def get_alternate_recipes():
	alternates = []
	for recipe in parser.recipes.values():
		if recipe.alternate_recipe:
			if not ALLOW_RELOAD and recipe.phase > 1:
				continue
			alternates.append({
				'id': recipe.id,
				'display_name': recipe.display_name,
				'building': recipe.building_type
			})
	return jsonify(sorted(alternates, key=lambda x: x['display_name']))

@app.route('/reload')
def reload_recipes():
  if not ALLOW_RELOAD:
    return jsonify({'status': 'error', 'message': 'Reload not available'}), 403
  global parser, calculator
  parser = RecipeParser(base_path)
  calculator = ProductionCalculator(parser.recipes)
  calculator.set_display_names(parser.display_name_map)
  return jsonify({'status': 'ok', 'recipe_count': len(parser.recipes)})

if __name__ == '__main__':
  app.run(debug=True, port=5000)