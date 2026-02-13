import os
import re
import json
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field

SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), 'recipes_snapshot.json')
try:
  from config import GAME_DATA_PATH
  base_path = GAME_DATA_PATH
except ImportError:
  base_path = None

@dataclass
class Recipe:
  id: str
  display_name: str
  inputs: Dict[str, int] = field(default_factory=dict)
  outputs: Dict[str, int] = field(default_factory=dict)
  production_time: float = 5.0
  building_type: str = ""
  required_research: str = ""
  energy_consumption: int = 5
  mana_consumption: float = 0.0
  phase: int = 1
  alternate_recipe: bool = False

@dataclass
class ProductionNode:
  resource: str
  quantity_per_minute: float
  recipe: Optional[Recipe]
  building_type: str
  building_count: float
  depth: int
  children: List['ProductionNode'] = field(default_factory=list)

class RecipeParser:
  def __init__(self, base_path: str):
    self.base_path = base_path
    self.recipes: Dict[str, Recipe] = {}
    self.resource_enum_map: Dict[str, str] = {}
    self.building_enum_map: Dict[str, str] = {}
    self.research_phase_map: Dict[str, int] = {}
    self._load_enums()
    self._load_research_phases()
    self._load_recipes()

  def _load_enums(self):
    """Parse ResourceSystem.ResourceType enum from resource_manager.gd"""
    project_root = os.path.dirname(self.base_path)
    resource_manager_path = os.path.join(project_root, "scripts", "resource_manager.gd")
    self.display_name_map = {}
    if os.path.exists(resource_manager_path):
      with open(resource_manager_path, 'r', encoding='utf-8') as f:
        content = f.read()
        enum_match = re.search(r'enum ResourceType \{([^}]+)\}', content, re.DOTALL)
        if enum_match:
          enum_body = enum_match.group(1)
          for line in enum_body.split('\n'):
            line = line.strip()
            if '=' in line and not line.startswith('//') and not line.startswith('#'):
              parts = line.split('=')
              name = parts[0].strip().rstrip(',')
              value_str = parts[1].split(',')[0].split('#')[0].strip()
              try:
                value = int(value_str)
                self.resource_enum_map[value] = name
              except ValueError:
                pass
        # Parse display names from resource_registry
        registry_match = re.search(r'static var resource_registry:.*?\{(.*?)^\}', content, re.DOTALL | re.MULTILINE)
        if registry_match:
          registry_content = registry_match.group(1)
          current_resource = None
          for line in registry_content.split('\n'):
            resource_match = re.search(r'ResourceType\.(\w+):', line)
            if resource_match:
              current_resource = resource_match.group(1)
            elif current_resource and '"display_name"' in line:
              display_match = re.search(r'"display_name":\s*"([^"]+)"', line)
              if display_match:
                self.display_name_map[current_resource] = display_match.group(1)
    print(f"Loaded {len(self.resource_enum_map)} resource type mappings")
    print(f"Loaded {len(self.display_name_map)} display name mappings")
    
    # Building types
    self.building_enum_map = {
      "MINER": "Miner",
      "SMELTER": "Smelter",
      "ASSEMBLER": "Assembler",
      "MANA_FORGE": "Mana Forge",
      "FLUID_EXTRACTOR": "Fluid Pump",
      "CRUSHER": "Crusher",
      "OILWORKS": "Oilworks"
    }

  def _load_research_phases(self):
    """Parse research files to get phase mappings"""
    project_root = os.path.dirname(self.base_path)
    research_path = os.path.join(project_root, "data", "research")
    if not os.path.exists(research_path):
      print(f"Warning: research path not found: {research_path}")
      return
    for filename in os.listdir(research_path):
      if filename.endswith('.tres'):
        filepath = os.path.join(research_path, filename)
        try:
          with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            id_match = re.search(r'id = "([^"]+)"', content)
            phase_match = re.search(r'phase = (\d+)', content)
            if id_match and phase_match:
              research_id = id_match.group(1)
              phase = int(phase_match.group(1))
              self.research_phase_map[research_id] = phase
        except Exception as e:
          print(f"Error parsing research {filepath}: {e}")
    print(f"Loaded {len(self.research_phase_map)} research phase mappings")

  def _parse_tres_file(self, filepath: str) -> Optional[Recipe]:
    """Parse a single .tres recipe file"""
    try:
      with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
      
      recipe = Recipe(id="", display_name="")
      
      # Parse basic fields
      id_match = re.search(r'id = "([^"]+)"', content)
      if id_match:
        recipe.id = id_match.group(1)
      
      name_match = re.search(r'display_name = "([^"]+)"', content)
      if name_match:
        recipe.display_name = name_match.group(1)
      else:
        recipe.display_name = recipe.id.replace('_', ' ').title()
      
      time_match = re.search(r'production_time = ([\d.]+)', content)
      if time_match:
        recipe.production_time = float(time_match.group(1))
      
      energy_match = re.search(r'energy_consumption = (\d+)', content)
      if energy_match:
        recipe.energy_consumption = int(energy_match.group(1))
      
      research_match = re.search(r'required_research = "([^"]*)"', content)
      if research_match:
        recipe.required_research = research_match.group(1)
      
      mana_match = re.search(r'mana_consumption = ([\d.]+)', content)
      if mana_match:
        recipe.mana_consumption = float(mana_match.group(1))

      alternate_match = re.search(r'alternate_recipe = (true|false)', content)
      if alternate_match:
        recipe.alternate_recipe = alternate_match.group(1) == 'true'

      # Parse inputs dictionary
      inputs_match = re.search(r'inputs = Dictionary\[int, int\]\(\{([^}]*)\}\)', content, re.DOTALL)
      if inputs_match:
        inputs_str = inputs_match.group(1)
        for line in inputs_str.split('\n'):
          line = line.strip().rstrip(',')
          int_match = re.search(r'(\d+):\s*(\d+)', line)
          if int_match:
            enum_value = int(int_match.group(1))
            amount = int(int_match.group(2))
            resource_name = self.resource_enum_map.get(enum_value)
            if resource_name:
              recipe.inputs[resource_name] = amount

      # Parse outputs dictionary
      outputs_match = re.search(r'outputs = Dictionary\[int, int\]\(\{([^}]*)\}\)', content, re.DOTALL)
      if outputs_match:
        outputs_str = outputs_match.group(1)
        for line in outputs_str.split('\n'):
          line = line.strip().rstrip(',')
          int_match = re.search(r'(\d+):\s*(\d+)', line)
          if int_match:
            enum_value = int(int_match.group(1))
            amount = int(int_match.group(2))
            resource_name = self.resource_enum_map.get(enum_value)
            if resource_name:
              recipe.outputs[resource_name] = amount
      
      # Determine building type from filepath
      building_folder = os.path.basename(os.path.dirname(filepath))
      recipe.building_type = building_folder.replace('_', ' ').title()
      if recipe.required_research:
        recipe.phase = self.research_phase_map.get(recipe.required_research, 1)
      else:
        recipe.phase = 1
      
      return recipe if recipe.id else None
    except Exception as e:
      print(f"Error parsing {filepath}: {e}")
      return None
  
  def _load_recipes(self):
    """Load all recipes from the data/recipes folder structure"""
    recipes_path = os.path.join(self.base_path, "recipes")
    if not os.path.exists(recipes_path):
      print(f"Warning: recipes path not found: {recipes_path}")
      return
    
    for building_folder in os.listdir(recipes_path):
      folder_path = os.path.join(recipes_path, building_folder)
      if os.path.isdir(folder_path):
        for filename in os.listdir(folder_path):
          if filename.endswith('.tres'):
            filepath = os.path.join(folder_path, filename)
            recipe = self._parse_tres_file(filepath)
            if recipe:
              self.recipes[recipe.id] = recipe

    print(f"Loaded {len(self.recipes)} recipes from {recipes_path}")

  def export_snapshot(self, output_path: str, timestamp=None):
    """Export all parsed data to JSON snapshot"""
    from datetime import datetime
    if timestamp is None:
      timestamp = datetime.now()
    snapshot = {
      'timestamp': timestamp.isoformat(),
      'recipes': {},
      'resource_enum_map': self.resource_enum_map,
      'display_name_map': self.display_name_map,
      'building_enum_map': self.building_enum_map,
      'research_phase_map': self.research_phase_map
    }
    for recipe_id, recipe in self.recipes.items():
      snapshot['recipes'][recipe_id] = {
        'id': recipe.id,
        'display_name': recipe.display_name,
        'inputs': recipe.inputs,
        'outputs': recipe.outputs,
        'production_time': recipe.production_time,
        'building_type': recipe.building_type,
        'required_research': recipe.required_research,
        'energy_consumption': recipe.energy_consumption,
        'mana_consumption': recipe.mana_consumption,
        'phase': recipe.phase,
        'alternate_recipe': recipe.alternate_recipe
      }
    with open(output_path, 'w', encoding='utf-8') as f:
      json.dump(snapshot, f, indent=2)
    print(f"Exported snapshot with {len(self.recipes)} recipes to {output_path}")

  @classmethod
  def from_snapshot(cls, snapshot_path: str):
    """Load recipes from JSON snapshot instead of parsing files"""
    instance = cls.__new__(cls)
    with open(snapshot_path, 'r', encoding='utf-8') as f:
      snapshot = json.load(f)
    instance.base_path = ""
    instance.snapshot_timestamp = snapshot.get('timestamp', 'Unknown')
    instance.resource_enum_map = snapshot['resource_enum_map']
    instance.display_name_map = snapshot['display_name_map']
    instance.building_enum_map = snapshot['building_enum_map']
    instance.research_phase_map = snapshot['research_phase_map']
    instance.recipes = {}
    for recipe_id, recipe_data in snapshot['recipes'].items():
      recipe = Recipe(
        id=recipe_data['id'],
        display_name=recipe_data['display_name'],
        inputs=recipe_data['inputs'],
        outputs=recipe_data['outputs'],
        production_time=recipe_data['production_time'],
        building_type=recipe_data['building_type'],
        required_research=recipe_data['required_research'],
        energy_consumption=recipe_data['energy_consumption'],
        mana_consumption=recipe_data['mana_consumption'],
        phase=recipe_data['phase'],
        alternate_recipe=recipe_data['alternate_recipe']
      )
      instance.recipes[recipe_id] = recipe
    print(f"Loaded {len(instance.recipes)} recipes from snapshot")
    return instance

class ProductionCalculator:
  BASE_RESOURCES = {'ORE', 'MAGIC_ESSENCE', 'SUNDROP', 'GOLD_ORE', 'ARCANE_CRYSTAL', 'COAL', 'CINDER', 'WATER', 'OIL', 'LIMESTONE',
                    'COPPER_ORE', 'TIN_ORE', 'SLAG', 'SILVER_ORE', 'CRYSTAL_ORE', 'ADAMANTINE_ORE', 'VOIDSTONE_ORE'}
  
  def __init__(self, recipes: Dict[str, Recipe]):
    self.recipes = recipes
    self.recipes_by_output: Dict[str, List[Recipe]] = defaultdict(list)
    self.display_name_map = {}
    self._index_recipes()

  def set_display_names(self, display_name_map: Dict[str, str]):
    self.display_name_map = display_name_map

  def get_display_name(self, resource: str) -> str:
    return self.display_name_map.get(resource, resource.replace('_', ' ').title())
  
  def _index_recipes(self):
    """Create an index of recipes by their output resources"""
    for recipe in self.recipes.values():
      for output_resource in recipe.outputs:
        self.recipes_by_output[output_resource].append(recipe)

  def get_best_recipe(self, resource: str, max_phase: int = 1, prefer_efficient: bool = True,
                    allow_alternate: bool = True, allowed_alternates: Optional[List[str]] = None) -> Optional[Recipe]:
    """Get the best recipe for producing a resource within phase constraints"""
    candidates = [r for r in self.recipes_by_output.get(resource, []) if r.phase <= max_phase]
    if not allow_alternate:
      candidates = [r for r in candidates if not r.alternate_recipe]
    elif allowed_alternates is not None:
      candidates = [r for r in candidates if not r.alternate_recipe or r.id in allowed_alternates]
    if not candidates:
      return None
    valid_candidates = []
    for recipe in candidates:
      all_inputs_producible = True
      for input_resource in recipe.inputs.keys():
        if input_resource not in self.BASE_RESOURCES:
          input_cost = self._get_raw_cost_recursive(input_resource, max_phase, allow_alternate, set())
          if input_cost >= 9999.0:
            all_inputs_producible = False
            break
      if all_inputs_producible:
        valid_candidates.append(recipe)
    if not valid_candidates:
      return None
    if prefer_efficient and len(valid_candidates) > 1:
      best_recipe = valid_candidates[0]
      best_raw_cost = float('inf')
      for recipe in valid_candidates:
        output_amount = recipe.outputs.get(resource, 1)
        raw_cost = 0.0
        for input_resource, input_amount in recipe.inputs.items():
          input_per_output = input_amount / output_amount
          if input_resource in self.BASE_RESOURCES:
            raw_cost += input_per_output
          else:
            input_cost = self._get_raw_cost_recursive(input_resource, max_phase, allow_alternate, set(), allowed_alternates)
            raw_cost += input_per_output * input_cost
        if raw_cost < best_raw_cost:
          best_raw_cost = raw_cost
          best_recipe = recipe
      return best_recipe
    return valid_candidates[0]

  def _get_raw_cost_recursive(self, resource: str, max_phase: int, allow_alternate: bool, visited: Set[str], allowed_alternates: Optional[List[str]] = None) -> float:
    """Recursively calculate the raw resource cost to produce 1 unit of a resource"""
    if resource in self.BASE_RESOURCES:
      return 1.0
    if resource in visited:
      return 999999.0
    visited.add(resource)
    recipe = self.get_best_recipe(resource, max_phase, prefer_efficient=False, allow_alternate=allow_alternate, allowed_alternates=allowed_alternates)
    if not recipe:
      visited.remove(resource)
      return 999999.0
    output_amount = recipe.outputs.get(resource, 1)
    total_cost = 0.0
    valid_inputs = 0
    for input_resource, input_amount in recipe.inputs.items():
      if input_resource == 'NONE':
        continue
      valid_inputs += 1
      input_per_output = input_amount / output_amount
      input_cost = self._get_raw_cost_recursive(input_resource, max_phase, allow_alternate, visited.copy(), allowed_alternates)
      total_cost += input_per_output * input_cost
    if valid_inputs == 0:
      visited.remove(resource)
      return 999999.0
    visited.remove(resource)
    return total_cost

  def calculate_production_chain(self, target_resource: str, target_quantity_per_minute: float,
                               max_phase: int = 1, allow_alternate: bool = True, allowed_alternates: Optional[List[str]] = None) -> ProductionNode:
    """Calculate complete production chain for target resource"""
    visited: Set[str] = set()
    return self._build_chain_recursive(target_resource, target_quantity_per_minute, visited, 0, max_phase,
                                       allow_alternate, allowed_alternates)

  def _build_chain_recursive(self, resource: str, quantity_per_minute: float, visited: Set[str], depth: int,
                           max_phase: int, allow_alternate: bool = True, allowed_alternates: Optional[List[str]] = None) -> ProductionNode:
    """Recursively build production chain"""
    if resource in self.BASE_RESOURCES:
      return ProductionNode(
        resource = resource,
        quantity_per_minute = quantity_per_minute,
        recipe = None,
        building_type = "Miner/Extractor",
        building_count = 0.0,
        depth = depth,
        children = []
      )
    if resource in visited:
      return ProductionNode(
        resource = resource,
        quantity_per_minute = quantity_per_minute,
        recipe = None,
        building_type = "CIRCULAR",
        building_count = 0.0,
        depth = depth,
        children = []
      )
    visited.add(resource)
    recipe = self.get_best_recipe(resource, max_phase, allow_alternate=allow_alternate, allowed_alternates=allowed_alternates)
    if not recipe:
      return ProductionNode(
        resource = resource,
        quantity_per_minute = quantity_per_minute,
        recipe = None,
        building_type = "NO RECIPE",
        building_count = 0.0,
        depth = depth,
        children = []
      )
    output_amount = recipe.outputs.get(resource, 1)
    items_per_cycle = output_amount
    cycles_per_minute = 60.0 / recipe.production_time
    items_per_minute_per_building = items_per_cycle * cycles_per_minute
    buildings_needed = quantity_per_minute / items_per_minute_per_building
    children = []
    for input_resource, input_amount in recipe.inputs.items():
      if input_resource == 'NONE':
        continue
      input_per_minute = (input_amount / output_amount) * quantity_per_minute
      child_visited = visited.copy()
      child_node = self._build_chain_recursive(input_resource, input_per_minute, child_visited, depth + 1, max_phase,
                                               allow_alternate, allowed_alternates)
      children.append(child_node)
    if not children and resource not in self.BASE_RESOURCES:
      visited.remove(resource)
      return ProductionNode(
        resource = resource,
        quantity_per_minute = quantity_per_minute,
        recipe = None,
        building_type = "NO RECIPE",
        building_count = 0.0,
        depth = depth,
        children = []
      )
    visited.remove(resource)
    return ProductionNode(
      resource = resource,
      quantity_per_minute = quantity_per_minute,
      recipe = recipe,
      building_type = recipe.building_type,
      building_count = buildings_needed,
      depth = depth,
      children = children
    )
  
  def get_resource_list(self) -> List[str]:
    """Get sorted list of all resources that can be produced"""
    resources = set()
    for recipe in self.recipes.values():
      resources.update(recipe.outputs.keys())
    return sorted(list(resources))

  def get_total_requirements(self, node: ProductionNode) -> Dict[str, Tuple[float, Dict[str, float]]]:
    """Calculate total raw resource requirements and building counts"""
    raw_resources: Dict[str, float] = defaultdict(float)
    buildings: Dict[str, float] = defaultdict(float)
    alternate_recipes: Set[str] = set()

    def traverse(n: ProductionNode):
      if n.recipe is None:
        if n.resource in self.BASE_RESOURCES:
          display_name = self.get_display_name(n.resource)
          raw_resources[display_name] += n.quantity_per_minute
      else:
        buildings[n.building_type] += n.building_count
        if n.recipe.alternate_recipe:
          alternate_recipes.add(n.recipe.display_name)
      for child in n.children:
        traverse(child)

    traverse(node)
    return {
      'raw_resources': dict(raw_resources),
      'buildings': dict(buildings),
      'alternate_recipes': sorted(list(alternate_recipes))
    }

def print_production_chain(node: ProductionNode, indent: int = 0):
  """Pretty print production chain"""
  prefix = "  " * indent
  
  if node.recipe:
    print(f"{prefix}[{node.building_type}] x{node.building_count:.2f}")
    print(f"{prefix}Recipe: {node.recipe.display_name}")
    inputs_str = " + ".join([f"{amt}x {res}" for res, amt in node.recipe.inputs.items()])
    outputs_str = " + ".join([f"{amt}x {res}" for res, amt in node.recipe.outputs.items()])
    print(f"{prefix}  {inputs_str} -> {outputs_str}")
    print(f"{prefix}  Produces: {node.quantity_per_minute:.2f} {node.resource}/min")
    print()
    
    for child in node.children:
      print_production_chain(child, indent + 1)
  else:
    print(f"{prefix}[BASE] {node.resource}: {node.quantity_per_minute:.2f}/min")
    print()

def main():
  # Parse recipes
  if base_path:
    parser = RecipeParser(base_path)
  else:
    parser = RecipeParser.from_snapshot(SNAPSHOT_PATH)
  
  if not parser.recipes:
    print("No recipes found! Check your base_path.")
    return
  
  # Create calculator
  calculator = ProductionCalculator(parser.recipes)
  
  # Interactive mode
  print("\n=== Arcaneering Production Calculator ===\n")
  print("Available resources:")
  resources = calculator.get_resource_list()
  for i, resource in enumerate(resources, 1):
    if i % 4 == 0:
      print(f"{resource}")
    else:
      print(f"{resource:<25}", end="")
  print("\n")
  
  while True:
    target = input("Enter target resource (or 'quit'): ").strip().upper()
    
    if target.lower() == 'quit':
      break
    
    if target not in resources:
      print(f"Resource '{target}' not found. Try again.")
      continue
    
    try:
      quantity = float(input("Enter desired quantity per minute: "))
    except ValueError:
      print("Invalid quantity. Try again.")
      continue
    
    print(f"\n=== Production Chain for {quantity:.2f} {target}/min ===\n")
    
    # Calculate chain
    chain = calculator.calculate_production_chain(target, quantity)
    
    # Print chain
    print_production_chain(chain)
    
    # Print totals
    totals = calculator.get_total_requirements(chain)
    
    print("=== TOTAL RAW RESOURCES REQUIRED ===")
    for resource, amount in sorted(totals['raw_resources'].items()):
      print(f"  {resource}: {amount:.2f}/min")
    
    print("\n=== TOTAL BUILDINGS REQUIRED ===")
    for building, count in sorted(totals['buildings'].items()):
      print(f"  {building}: {count:.2f}")
    
    print("\n" + "="*50 + "\n")

if __name__ == "__main__":
  main()
