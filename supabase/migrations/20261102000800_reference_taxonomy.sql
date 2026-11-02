-- Model Room: prop market categories
-- These are labels for kinds of player props, not sports data.

insert into public.prop_markets (key, league, label, unit) values
  ('nfl.passing_yards',     'nfl', 'Passing yards',     'yards'),
  ('nfl.passing_touchdowns','nfl', 'Passing touchdowns','touchdowns'),
  ('nfl.rushing_yards',     'nfl', 'Rushing yards',     'yards'),
  ('nfl.receiving_yards',   'nfl', 'Receiving yards',   'yards'),
  ('nfl.receptions',        'nfl', 'Receptions',        'receptions'),
  ('nba.points',            'nba', 'Points',            'points'),
  ('nba.rebounds',          'nba', 'Rebounds',          'rebounds'),
  ('nba.assists',           'nba', 'Assists',           'assists'),
  ('nba.threes_made',       'nba', '3-pointers made',   'threes'),
  ('nba.points_rebounds_assists', 'nba', 'Points + rebounds + assists', 'points');
