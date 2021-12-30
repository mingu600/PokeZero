from collections import defaultdict
from copy import copy, deepcopy
import numpy as np
import constants
from data import all_move_json


boost_multiplier_lookup = {
    -6: 2/8,
    -5: 2/7,
    -4: 2/6,
    -3: 2/5,
    -2: 2/4,
    -1: 2/3,
    0: 2/2,
    1: 3/2,
    2: 4/2,
    3: 5/2,
    4: 6/2,
    5: 7/2,
    6: 8/2
}


class State(object):
    # __slots__ = ('self', 'opponent', 'weather', 'field', 'trick_room', 'weather_count', 'terrain_count')

    def __init__(self, user, opponent, weather, field, trick_room, weather_count, terrain_count):
        self.self = user
        self.opponent = opponent
        self.weather = weather
        self.weather_count = weather_count
        self.field = field
        self.trick_room = trick_room
        self.terrain_count = terrain_count

    def __deepcopy__(self, memo):
        result = State(self.self, self.opponent, self.weather, self.field, self.trick_room, self.weather_count, self.terrain_count)
        memo[id(self)] = result
        for k, v in self.__dict__.items():
            setattr(result, k, deepcopy(v, memo)) # Copy over attributes by copying directly or in case of complex objects like lists for exaample calling the `__deepcopy()__` method defined by them. Thus recursively copying the whole tree of objects.
        return result

    def get_self_options(self):
        if self.self.active.hp <= 0:
            possible_moves = []
        else:
            possible_moves = [m[constants.ID] for m in self.self.active.moves if not m[constants.DISABLED]]

        if self.self.trapped(self.opponent.active) and self.self.active.hp > 0:
            possible_switches = []
        else:
            possible_switches = self.self.get_switches()

        if self.self.active.hp > 0 and self.opponent.active.hp <= 0:
            return ['splash']
        return possible_moves + possible_switches

    def get_all_self_options(self):
        switches = []
        for pkmn_name, pkmn in self.self.reserve.items():
            switches.append("{} {}".format(constants.SWITCH_STRING, pkmn_name))
        return [m[constants.ID] for m in self.self.active.moves] + switches

    def get_opponent_options(self):
        if self.opponent.active.hp <= 0:
            possible_moves = []
        else:
            possible_moves = [m[constants.ID] for m in self.opponent.active.moves if not m[constants.DISABLED]]

        if self.opponent.trapped(self.self.active):
            possible_switches = []
        else:
            possible_switches = self.opponent.get_switches()
        if self.self.opponent.active.hp > 0 and self.self.active.hp <= 0:
            return ['splash']
        return possible_moves + possible_switches

    def get_all_options(self):
        force_switch = self.self.active.hp <= 0
        wait = self.opponent.active.hp <= 0

        # double faint or team preview
        if force_switch and wait:
            user_options = self.get_self_options(force_switch) or [constants.DO_NOTHING_MOVE]
            opponent_options = self.get_opponent_options() or [constants.DO_NOTHING_MOVE]
            return user_options, opponent_options

        if force_switch:
            opponent_options = [constants.DO_NOTHING_MOVE]
        else:
            opponent_options = self.get_opponent_options()

        if wait:
            user_options = [constants.DO_NOTHING_MOVE]
        else:
            user_options = self.get_self_options(force_switch)

        if not user_options:
            user_options = [constants.DO_NOTHING_MOVE]

        if not opponent_options:
            opponent_options = [constants.DO_NOTHING_MOVE]

        return user_options, opponent_options

    def battle_is_finished(self):
        # Returns:
        #    1 if the bot (self) has won
        #   -1 if the opponent has won
        #    False if the battle is not over
        if self.self.active.hp <1 and not any(pkmn.hp for pkmn in self.self.reserve.values()):
            return -1
        elif not any(pkmn.hp for pkmn in self.self.reserve.values()) and sum([x['disabled'] for x in self.self.active.moves]) == 4:
            return -1
        elif self.opponent.active.hp < 1 and not any(pkmn.hp for pkmn in self.opponent.reserve.values()):
            return 1

        elif not any(pkmn.hp for pkmn in self.opponent.reserve.values()) and sum([x['disabled'] for x in self.opponent.active.moves]) == 4:
            return 1

        else:
            self_disabled = sum([x['disabled'] for x in self.self.active.moves])
            opp_disabled = sum([x['disabled'] for x in self.opponent.active.moves])
            if self_disabled == 4 or opp_disabled == 4:
                self_pp = 0
                for pkmn in self.self.reserve.values():
                    for move in pkmn.moves:
                        self_pp += move['current_pp']

                opp_pp = 0
                for pkmn in self.opponent.reserve.values():
                    for move in pkmn.moves:
                        opp_pp += move['current_pp']
                if opp_disabled == 4 and self_pp > 0:
                    return 1
                elif self_disabled == 4 and opp_pp > 0:
                    return -1

        return False

    @classmethod
    def from_dict(cls, state_dict):
        return State(
            Side.from_dict(state_dict[constants.SELF]),
            Side.from_dict(state_dict[constants.OPPONENT]),
            state_dict[constants.WEATHER],
            state_dict[constants.FIELD],
            state_dict[constants.TRICK_ROOM]
        )

    def __repr__(self):
        return str(
            {
                constants.SELF: self.self,
                constants.OPPONENT: self.opponent,
                constants.WEATHER: self.weather,
                constants.FIELD: self.field,
                constants.TRICK_ROOM: self.trick_room
            }
        )


class Side(object):
    __slots__ = ('active', 'reserve', 'wish', 'side_conditions', 'ls_count', 'ref_count', 'av_count')

    def __init__(self, active, reserve, wish, side_conditions, ls_count=0, ref_count=0,av_count=0):
        self.active = active
        self.reserve = reserve
        self.wish = wish
        self.side_conditions = side_conditions
        self.ls_count = ls_count
        self.ref_count = ref_count
        self.av_count = av_count

    def get_switches(self):
        switches = []
        for pkmn_name, pkmn in self.reserve.items():
            if pkmn.hp > 0:
                switches.append("{} {}".format(constants.SWITCH_STRING, pkmn_name))
        return switches

    def trapped(self, opponent_active):
        if self.active.item == 'shedshell' or 'ghost' in self.active.types:
            return False
        elif constants.PARTIALLY_TRAPPED in self.active.volatile_status and self.active.part_trapped_counter > 0:
            return True
        elif opponent_active.ability == 'shadowtag':
            return True
        elif opponent_active.ability == 'magnetpull' and 'steel' in self.active.types:
            return True
        elif opponent_active.ability == 'arenatrap' and self.active.is_grounded():
            return True
        else:
            return False

    @classmethod
    def from_dict(cls, side_dict):
        return Side(
            Pokemon.from_dict(side_dict[constants.ACTIVE]),
            {p[constants.ID]: Pokemon.from_dict(p) for p in side_dict[constants.RESERVE].values()},
            side_dict[constants.WISH],
            defaultdict(int, side_dict[constants.SIDE_CONDITIONS])
        )

    def __repr__(self):
        return str({
            constants.ACTIVE: self.active,
            constants.RESERVE: self.reserve,
            constants.WISH: self.wish,
            constants.SIDE_CONDITIONS: dict(self.side_conditions)
        })


class Pokemon(object):
    __slots__ = (
        'id',
        'level',
        'types',
        'hp',
        'maxhp',
        'ability',
        'item',
        'attack',
        'defense',
        'special_attack',
        'special_defense',
        'speed',
        'nature',
        'evs',
        'attack_boost',
        'defense_boost',
        'special_attack_boost',
        'special_defense_boost',
        'speed_boost',
        'accuracy_boost',
        'evasion_boost',
        'status',
        'volatile_status',
        'moves',
        'substitute_hp',
        'part_trapped_counter',
        'burn_multiplier'
    )
    def __init__(self,
                 identifier,
                 level,
                 types,
                 hp,
                 maxhp,
                 ability,
                 item,
                 attack,
                 defense,
                 special_attack,
                 special_defense,
                 speed,
                 nature="serious",
                 evs=(85,) * 6,
                 attack_boost=0,
                 defense_boost=0,
                 special_attack_boost=0,
                 special_defense_boost=0,
                 speed_boost=0,
                 accuracy_boost=0,
                 evasion_boost=0,
                 status=None,
                 volatile_status=None,
                 moves=None,
                 substitute_hp=0,
                 trapped_counter=0):
        self.id = identifier
        self.level = level
        self.types = types
        self.hp = hp
        self.maxhp = maxhp
        self.ability = ability
        self.item = item
        self.attack = attack
        self.defense = defense
        self.special_attack = special_attack
        self.special_defense = special_defense
        self.speed = speed
        self.nature = nature
        self.evs = evs
        self.attack_boost = attack_boost
        self.defense_boost = defense_boost
        self.special_attack_boost = special_attack_boost
        self.special_defense_boost = special_defense_boost
        self.speed_boost = speed_boost
        self.accuracy_boost = accuracy_boost
        self.evasion_boost = evasion_boost
        self.status = status
        self.volatile_status = volatile_status or set()
        self.moves = moves or list()
        self.part_trapped_counter = trapped_counter
        self.substitute_hp = substitute_hp

        # evaluation relies on a multiplier for the burn status
        # it is calculated here to save time during evaluation
        self.burn_multiplier = self.calculate_burn_multiplier()

    def calculate_burn_multiplier(self):
        # this will result in a positive evaluation for a burned pokemon
        if self.ability in ['guts', 'marvelscale', 'quickfeet']:
            return -2

        # +1 to the multiplier for each physical move
        burn_multiplier = len([m for m in self.moves if all_move_json[m[constants.ID]][constants.CATEGORY] == constants.PHYSICAL])

        # evaluation could use more than 4 moves for opponent's pokemon - dont go over 4
        burn_multiplier = min(4, burn_multiplier)

        # dont make this as punishing for special attackers
        if self.special_attack > self.attack:
            burn_multiplier = int(burn_multiplier / 2)

        return burn_multiplier

    def item_can_be_removed(self):
        if (
            self.item is None or
            self.ability == 'stickyhold' or
            'substitute' in self.volatile_status or
            self.id in constants.POKEMON_CANNOT_HAVE_ITEMS_REMOVED or
            self.id.endswith('mega') and self.id != 'yanmega' or  # yeah this is hacky but who are you to judge?
            self.id.startswith("genesect") and self.item.endswith("drive") or
            self.id.startswith("arceus") and self.item.endswith("plate") or
            self.id.startswith("silvally") and self.item.endswith("memory") or
            # any(self.id.startswith(i) and self.id != i for i in constants.UNKOWN_POKEMON_FORMES) or
            self.item.endswith('iumz')
        ):
            return False

        return True

    @classmethod
    def from_state_pokemon_dict(cls, d):
        return Pokemon(
            d[constants.ID],
            d[constants.LEVEL],
            d[constants.TYPES],
            d[constants.HITPOINTS],
            d[constants.MAXHP],
            d[constants.ABILITY],
            d[constants.ITEM],
            d[constants.STATS][constants.ATTACK],
            d[constants.STATS][constants.DEFENSE],
            d[constants.STATS][constants.SPECIAL_ATTACK],
            d[constants.STATS][constants.SPECIAL_DEFENSE],
            d[constants.STATS][constants.SPEED],
            d[constants.NATURE],
            d[constants.EVS],
            d[constants.BOOSTS][constants.ATTACK],
            d[constants.BOOSTS][constants.DEFENSE],
            d[constants.BOOSTS][constants.SPECIAL_ATTACK],
            d[constants.BOOSTS][constants.SPECIAL_DEFENSE],
            d[constants.BOOSTS][constants.SPEED],
            d[constants.BOOSTS][constants.ACCURACY],
            d[constants.BOOSTS][constants.EVASION],
            d[constants.STATUS],
            d[constants.VOLATILE_STATUS],
            d[constants.MOVES]
        )

    @classmethod
    def from_dict(cls, d):
        return Pokemon(
            d[constants.ID],
            d[constants.LEVEL],
            d[constants.TYPES],
            d[constants.HITPOINTS],
            d[constants.MAXHP],
            d[constants.ABILITY],
            d[constants.ITEM],
            d[constants.ATTACK],
            d[constants.DEFENSE],
            d[constants.SPECIAL_ATTACK],
            d[constants.SPECIAL_DEFENSE],
            d[constants.SPEED],
            d[constants.NATURE],
            d[constants.EVS],
            d[constants.ATTACK_BOOST],
            d[constants.DEFENSE_BOOST],
            d[constants.SPECIAL_ATTACK_BOOST],
            d[constants.SPECIAL_DEFENSE_BOOST],
            d[constants.SPEED_BOOST],
            d.get(constants.ACCURACY_BOOST, 0),
            d.get(constants.EVASION_BOOST, 0),
            d[constants.STATUS],
            set(d[constants.VOLATILE_STATUS]),
            d[constants.MOVES]
        )

    def calculate_boosted_stats(self):
        return {
            constants.ATTACK: boost_multiplier_lookup[self.attack_boost] * self.attack,
            constants.DEFENSE: boost_multiplier_lookup[self.defense_boost] * self.defense,
            constants.SPECIAL_ATTACK: boost_multiplier_lookup[self.special_attack_boost] * self.special_attack,
            constants.SPECIAL_DEFENSE: boost_multiplier_lookup[self.special_defense_boost] * self.special_defense,
            constants.SPEED: boost_multiplier_lookup[self.speed_boost] * self.speed,
        }

    def is_grounded(self):
        if 'flying' in self.types or self.ability == 'levitate' or self.item == 'airballoon':
            return False
        return True

    def __repr__(self):
        return str({
                constants.ID: self.id,
                constants.LEVEL: self.level,
                constants.TYPES: self.types,
                constants.HITPOINTS: self.hp,
                constants.MAXHP: self.maxhp,
                constants.ABILITY: self.ability,
                constants.ITEM: self.item,
                constants.ATTACK: self.attack,
                constants.DEFENSE: self.defense,
                constants.SPECIAL_ATTACK: self.special_attack,
                constants.SPECIAL_DEFENSE: self.special_defense,
                constants.SPEED: self.speed,
                constants.NATURE: self.nature,
                constants.EVS: self.evs,
                constants.ATTACK_BOOST: self.attack_boost,
                constants.DEFENSE_BOOST: self.defense_boost,
                constants.SPECIAL_ATTACK_BOOST: self.special_attack_boost,
                constants.SPECIAL_DEFENSE_BOOST: self.special_defense_boost,
                constants.SPEED_BOOST: self.speed_boost,
                constants.ACCURACY_BOOST: self.accuracy_boost,
                constants.EVASION_BOOST: self.evasion_boost,
                constants.STATUS: self.status,
                constants.VOLATILE_STATUS: list(self.volatile_status),
                constants.MOVES: self.moves,
                "part_trapped_counter": self.part_trapped_counter,
                "substitute_hp": self.substitute_hp
            })


class TransposeInstruction:
    __slots__ = ('percentage', 'instructions', 'frozen')

    def __init__(self, percentage, instructions, frozen=False):
        self.percentage = percentage
        self.instructions = instructions
        self.frozen = frozen

    def update_percentage(self, modifier):
        self.percentage *= modifier

    def add_instruction(self, instruction):
        self.instructions.append(instruction)

    def has_same_instructions_as(self, other):
        return self.instructions == other.instructions

    def __copy__(self):
        return TransposeInstruction(self.percentage, copy(self.instructions), self.frozen)

    def __repr__(self):
        return "{}: {}".format(self.percentage, str(self.instructions))

    def __eq__(self, other):
        return self.percentage == other.percentage and \
            self.instructions == other.instructions and \
            self.frozen == other.frozen


class StateMutator:

    def __init__(self, state):
        self.state = state
        self.apply_instructions = {
            constants.MUTATOR_SWITCH: self.switch,
            constants.MUTATOR_APPLY_VOLATILE_STATUS: self.apply_volatile_status,
            constants.MUTATOR_REMOVE_VOLATILE_STATUS: self.remove_volatile_status,
            constants.MUTATOR_DAMAGE: self.damage,
            constants.MUTATOR_HEAL: self.heal,
            constants.MUTATOR_BOOST: self.boost,
            constants.MUTATOR_UNBOOST: self.unboost,
            constants.MUTATOR_APPLY_STATUS: self.apply_status,
            constants.MUTATOR_REMOVE_STATUS: self.remove_status,
            constants.MUTATOR_SIDE_START: self.side_start,
            constants.MUTATOR_SIDE_END: self.side_end,
            constants.MUTATOR_WISH_START: self.start_wish,
            constants.MUTATOR_WISH_DECREMENT: self.decrement_wish,
            constants.MUTATOR_DISABLE_MOVE: self.disable_move,
            constants.MUTATOR_ENABLE_MOVE: self.enable_move,
            constants.MUTATOR_WEATHER_START: self.start_weather,
            constants.MUTATOR_FIELD_START: self.start_field,
            constants.MUTATOR_FIELD_END: self.end_field,
            constants.MUTATOR_TOGGLE_TRICKROOM: self.toggle_trickroom,
            constants.MUTATOR_CHANGE_TYPE: self.change_types,
            constants.MUTATOR_CHANGE_ITEM: self.change_item,
            constants.MUTATOR_CHANGE_STATS: self.change_stats,
            'subtract_part_trapped': self.subtract_part_trapped,
            'subtract_substitute_hp': self.subtract_substitute_hp,
            'increment_weather': self.increment_weather,
            "increment_terrain": self.increment_terrain,
            'increment_ls_counter': self.increment_ls_counter,
            'increment_av_counter': self.increment_av_counter,
            'increment_reflect_counter': self.increment_reflect_counter,
            'decrement_pp': self.decrement_pp
        }
        self.reverse_instructions = {
            constants.MUTATOR_SWITCH: self.reverse_switch,
            constants.MUTATOR_APPLY_VOLATILE_STATUS: self.remove_volatile_status,
            constants.MUTATOR_REMOVE_VOLATILE_STATUS: self.apply_volatile_status,
            constants.MUTATOR_DAMAGE: self.heal,
            constants.MUTATOR_HEAL: self.damage,
            constants.MUTATOR_BOOST: self.unboost,
            constants.MUTATOR_UNBOOST: self.boost,
            constants.MUTATOR_APPLY_STATUS: self.remove_status,
            constants.MUTATOR_REMOVE_STATUS: self.apply_status,
            constants.MUTATOR_SIDE_START: self.reverse_side_start,
            constants.MUTATOR_SIDE_END: self.reverse_side_end,
            constants.MUTATOR_WISH_START: self.reserve_start_wish,
            constants.MUTATOR_WISH_DECREMENT: self.reverse_decrement_wish,
            constants.MUTATOR_DISABLE_MOVE: self.enable_move,
            constants.MUTATOR_ENABLE_MOVE: self.disable_move,
            constants.MUTATOR_WEATHER_START: self.reverse_start_weather,
            constants.MUTATOR_FIELD_START: self.reverse_start_field,
            constants.MUTATOR_FIELD_END: self.reverse_end_field,
            constants.MUTATOR_TOGGLE_TRICKROOM: self.toggle_trickroom,
            constants.MUTATOR_CHANGE_TYPE: self.reverse_change_types,
            constants.MUTATOR_CHANGE_ITEM: self.reverse_change_item,
            constants.MUTATOR_CHANGE_STATS: self.reverse_change_stats,
            'subtract_part_trapped': self.add_part_trapped,
            'subtract_substitute_hp': self.add_substitute_hp,
            "increment_weather": self.decrement_weather,
            "increment_terrain": self.decrement_terrain,
            'increment_ls_counter': self.decrement_ls_counter,
            'increment_av_counter': self.decrement_av_counter,
            'increment_reflect_counter': self.decrement_reflect_counter,
            'decrement_pp': self.increment_pp
        }

    def __deepcopy__(self, memo):
        result = StateMutator(self.state)
        memo[id(self)] = result
        for k, v in self.__dict__.items():
            setattr(result, k, deepcopy(v, memo)) # Copy over attributes by copying directly or in case of complex objects like lists for exaample calling the `__deepcopy()__` method defined by them. Thus recursively copying the whole tree of objects.
        return result

    def apply_one(self, instruction):
        method = self.apply_instructions[instruction[0]]
        method(*instruction[1:])

    def apply(self, instructions):
        for instruction in instructions:
            method = self.apply_instructions[instruction[0]]
            method(*instruction[1:])

    def reverse(self, instructions):
        for instruction in reversed(instructions):
            method = self.reverse_instructions[instruction[0]]
            method(*instruction[1:])

    def get_side(self, side):
        return getattr(self.state, side)

    def decrement_pp(self, side, move_name, amount):
        side = self.get_side(side)
        try:
            move = next(filter(lambda x: x[constants.ID] == move_name, side.active.moves))
        except StopIteration:
            raise ValueError("{} not in pokemon's moves: {}".format(move_name, side.active.moves))

        move['current_pp'] -= amount

    def increment_pp(self, side, move_name, amount):
        side = self.get_side(side)
        try:
            move = next(filter(lambda x: x[constants.ID] == move_name, side.active.moves))
        except StopIteration:
            raise ValueError("{} not in pokemon's moves: {}".format(move_name, side.active.moves))

        move['current_pp'] += amount

    def disable_move(self, side, move_name):
        side = self.get_side(side)
        try:
            move = next(filter(lambda x: x[constants.ID] == move_name, side.active.moves))
        except StopIteration:
            raise ValueError("{} not in pokemon's moves: {}".format(move_name, side.active.moves))

        move[constants.DISABLED] = True

    def enable_move(self, side, move_name):
        side = self.get_side(side)
        try:
            move = next(filter(lambda x: x[constants.ID] == move_name, side.active.moves))
        except StopIteration:
            raise ValueError("{} not in pokemon's moves: {}".format(move_name, side.active.moves))

        move[constants.DISABLED] = False

    def switch(self, side, _, switch_pokemon_name):
        # the second parameter to this function is the current active pokemon
        # this value must be here for reversing purposes
        side = self.get_side(side)

        side.reserve[side.active.id] = side.active
        side.active = side.reserve.pop(switch_pokemon_name)

    def reverse_switch(self, side, previous_active, current_active):
        self.switch(side, current_active, previous_active)

    def apply_volatile_status(self, side, volatile_status):
        side = self.get_side(side)
        side.active.volatile_status.add(volatile_status)
        if volatile_status == constants.PARTIALLY_TRAPPED and side.active.part_trapped_counter == 0:
            side.active.part_trapped_counter = 4

    def remove_volatile_status(self, side, volatile_status):
        side = self.get_side(side)
        if volatile_status == constants.PARTIALLY_TRAPPED:
            side.active.part_trapped_counter = 0
        side.active.volatile_status.remove(volatile_status)

    def subtract_part_trapped(self, side, count):
        side = self.get_side(side)
        side.active.part_trapped_counter -= count

    def add_part_trapped(self, side, count):
        side = self.get_side(side)
        side.active.part_trapped_counter += count

    def subtract_substitute_hp(self, side, dmg):
        side = self.get_side(side)
        side.active.substitute_hp -= dmg

    def add_substitute_hp(self, side, dmg):
        side = self.get_side(side)
        side.active.substitute_hp += dmg

    def damage(self, side, amount):
        side = self.get_side(side)
        side.active.hp -= amount
        side.active.hp = np.floor(side.active.hp)

    def heal(self, side, amount):
        side = self.get_side(side)
        side.active.hp += amount
        side.active.hp = np.ceil(side.active.hp)

    def boost(self, side, stat, amount):
        side = self.get_side(side)
        if stat == constants.ATTACK:
            side.active.attack_boost += amount
        elif stat == constants.DEFENSE:
            side.active.defense_boost += amount
        elif stat == constants.SPECIAL_ATTACK:
            side.active.special_attack_boost += amount
        elif stat == constants.SPECIAL_DEFENSE:
            side.active.special_defense_boost += amount
        elif stat == constants.SPEED:
            side.active.speed_boost += amount
        elif stat == constants.ACCURACY:
            side.active.accuracy_boost += amount
        elif stat == constants.EVASION:
            side.active.evasion_boost += amount
        else:
            raise ValueError("Invalid stat: {}".format(stat))

    def unboost(self, side, stat, amount):
        self.boost(side, stat, -1*amount)

    def apply_status(self, side, status):
        side = self.get_side(side)
        side.active.status = status

    def remove_status(self, side, _):
        # the second parameter of this function is the status being removed
        # this value must be here for reverse purposes
        self.apply_status(side, None)

    def side_start(self, side, effect, amount):
        side = self.get_side(side)
        side.side_conditions[effect] += amount

    def reverse_side_start(self, side, effect, amount):
        side = self.get_side(side)
        side.side_conditions[effect] -= amount

    def side_end(self, side, effect, amount):
        side = self.get_side(side)
        side.side_conditions[effect] -= amount

    def reverse_side_end(self, side, effect, amount):
        self.side_start(side, effect, amount)

    def start_wish(self, side, health, _):
        # the third parameter is the current wish amount
        # it is here for reversing purposes
        side = self.get_side(side)
        side.wish = (2, health)

    def reserve_start_wish(self, side, _, previous_wish_amount):
        side = self.get_side(side)
        side.wish = (0, previous_wish_amount)

    def decrement_wish(self, side):
        side = self.get_side(side)
        side.wish = (side.wish[0] - 1, side.wish[1])

    def reverse_decrement_wish(self, side):
        side = self.get_side(side)
        side.wish = (side.wish[0] + 1, side.wish[1])

    def start_weather(self, weather, _):
        # the second parameter is the current weather
        # the value is here for reversing purposes
        self.state.weather = weather

    def reverse_start_weather(self, _, old_weather):
        self.state.weather = old_weather

    def decrement_weather(self, count):
        self.state.weather_count -= count

    def increment_weather(self, count):
        self.state.weather_count += count

    def decrement_terrain(self, count):
        self.state.terrain_count -= count

    def increment_terrain(self, count):
        self.state.terrain_count += count

    def decrement_ls_counter(self, side, count):
        side = self.get_side(side)
        side.ls_count -= count

    def increment_ls_counter(self, side, count):
        side = self.get_side(side)
        side.ls_count += count

    def decrement_reflect_counter(self, side, count):
        side = self.get_side(side)
        side.ref_count -= count

    def increment_reflect_counter(self, side, count):
        side = self.get_side(side)
        side.ref_count += count

    def decrement_av_counter(self, side, count):
        side = self.get_side(side)
        side.av_count -= count

    def increment_av_counter(self, side, count):
        side = self.get_side(side)
        side.av_count += count

    def start_field(self, field, _):
        # the second parameter is the current field
        # the value is here for reversing purposes
        self.state.field = field

    def reverse_start_field(self, _, old_field):
        self.state.field = old_field

    def end_field(self, _):
        # the second parameter is the current field
        # the value is here for reversing purposes
        self.state.field = None

    def reverse_end_field(self, old_field):
        self.state.field = old_field

    def toggle_trickroom(self):
        self.state.trick_room ^= True

    def change_types(self, side, new_types, _):
        # the third parameter is the current types of the active pokemon
        # they must be here for reversing purposes
        side = self.get_side(side)
        side.active.types = new_types

    def reverse_change_types(self, side, _, old_types):
        side = self.get_side(side)
        side.active.types = old_types

    def change_item(self, side, new_item, _):
        # the third parameter is the current item
        # it must be here for reversing purposes
        side = self.get_side(side)
        side.active.item = new_item

    def reverse_change_item(self, side, _, old_item):
        side = self.get_side(side)
        side.active.item = old_item

    def change_stats(self, side, new_stats, _):
        # the third parameter is the old stats
        # is must be here for reversing purposes
        side = self.get_side(side)
        side.active.maxhp = new_stats[0]
        side.active.attack = new_stats[1]
        side.active.defense = new_stats[2]
        side.active.special_attack = new_stats[3]
        side.active.special_defense = new_stats[4]
        side.active.speed = new_stats[5]

    def reverse_change_stats(self, side, _, old_stats):
        # the second parameter are the new stats
        side = self.get_side(side)
        side.active.maxhp = old_stats[0]
        side.active.attack = old_stats[1]
        side.active.defense = old_stats[2]
        side.active.special_attack = old_stats[3]
        side.active.special_defense = old_stats[4]
        side.active.speed = old_stats[5]
