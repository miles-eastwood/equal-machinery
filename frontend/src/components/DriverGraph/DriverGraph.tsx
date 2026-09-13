// src/components/DriverGraph.tsx

/* IMPORTS */
import { JSX, useEffect, useState, useRef, useMemo, useCallback } from 'react';
import cytoscape, { Core, EdgeSingular, EventObject, NodeSingular } from 'cytoscape';
import CytoscapeComponent from 'react-cytoscapejs';
import coseBilkent from 'cytoscape-cose-bilkent';
import {
  NodeData,
  EdgeData,
  YearsByCtor,
  TeammatesByYearByCtor,
  CtorData,
} from './DriverGraph.types';
import { Range, Direction, getTrackBackground } from 'react-range';

/* STATIC JSON */
import nodePositionJSON from '../../data/nodePositions.json';
import ctorMapJSON from '../../data/ctorMap.json';

/* CSS */
import './DriverGraph.css';

cytoscape.use(coseBilkent);

/* GLOBAL CONSTANTS */
const DEFAULT_MIN_DISPLAY_YEAR = 2024;
const DEFAULT_MAX_DISPLAY_YEAR = new Date().getFullYear();
const DEFAULT_MIN_DISPLAY_RACE_COUNT = 5;
const NODE_HOVER_SCALE = 1.5;
const DEFAULT_NODE_DIAMETER = computeNodeDiameter();
const TIMELINE_MIN_YEAR = 1970;
const TIMELINE_MAX_YEAR = new Date().getFullYear();

const ctorMap: Record<string, CtorData> = Object.fromEntries(
  ctorMapJSON.map(({ id, ...rest }) => [id, rest])
);

/* HELPER FUNCTIONS */

function getMostCommonCtorId(
  yearsByCtor: YearsByCtor[],
  yearMin: number = 0,
  yearMax: number = 9999
): string {
  let defaultCtorId: string = '0';
  if (yearsByCtor.length !== 0) {
    defaultCtorId = yearsByCtor.at(-1)!.ctorId;
    let maxCount = yearsByCtor
      .at(-1)!
      .years.filter((year) => yearMin <= year && year <= yearMax).length;

    for (let i = yearsByCtor.length - 2; i >= 0; --i) {
      let count = yearsByCtor[i].years.filter((year) => yearMin <= year && year <= yearMax).length;
      if (count > maxCount) {
        maxCount = count;
        defaultCtorId = yearsByCtor[i].ctorId;
      }
    }
  }

  return defaultCtorId;
}

// updateNodeVisibility(cy, minRaceCount, minYear, maxYear)
//  Changes node visibility based on parameters
//    Visible nodes must have at least one active year in [minYear, maxYear],
//      and must have at least minRaceCount races (overall, not in year range)
//  Also updates which displayCtor (used for coloring)
function updateNodeVisibility(
  cy: cytoscape.Core,
  minRaceCount: number,
  minYear: number,
  maxYear: number
): void {
  cy.nodes().forEach((node: NodeSingular) => {
    const ctorId: string = getMostCommonCtorId(node.data('yearsByCtor'), minYear, maxYear);
    node.data('displayCtorId', ctorId);

    const yearsByCtor: YearsByCtor[] = node.data('yearsByCtor');
    if (
      node.data('raceCount') >= minRaceCount &&
      yearsByCtor.some((ctor) => ctor.years.some((year) => minYear <= year && year <= maxYear))
    ) {
      node.show();
    } else {
      node.hide();
    }
  });
}

// centerViewport(cy) fits the frame to the current visible elements, and adjust the zoom accordingly
function centerViewport(cy: Core | null) {
  if (!cy) return;
  cy.fit(cy.elements(':visible'), 30); // fit to visible elements
  const fitZoom = cy.zoom();
  cy.minZoom(fitZoom * 0.85);
  cy.maxZoom(fitZoom * 5);
}

// computes node diameter for styling
// TODO: Right now this is literally just a constant, maybe switch to parameters with defaults?
function computeNodeDiameter(): number {
  const length = 3;
  const fontSize = 14;
  const charWidth = fontSize * 0.6; // rough average
  const textWidth = length * charWidth;
  const textHeight = fontSize * 1.25; // account for vertical padding
  return Math.max(textWidth, textHeight) + 30; // add padding
}

// saves current node positions to JSON file.
//  used to tweak layout for preset
function savePositions(cy: Core | null) {
  if (!cy) return;

  const positions = cy.nodes().reduce((acc, node) => {
    acc[node.id()] = node.position(); // { x, y }
    return acc;
  }, {} as Record<string, { x: number; y: number }>);

  const blob = new Blob([JSON.stringify(positions, null, 2)], {
    type: 'application/json',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'nodePositions.json';
  a.click();
  URL.revokeObjectURL(url);
}

// Promotes node / edge so that it will render above all other nodes / edges
function addElementToForeground(element: any): void {
  try {
    element._private.rscratch.inDragLayer = true;
  } catch (e) {
    console.warn('addElementToForeground fail');
  }
}

// Demotes node / edge so that it will no longer render above all other nodes / edges
function removeElementFromForeground(element: any): void {
  try {
    element._private.rscratch.inDragLayer = false;
  } catch (e) {
    console.warn('removeElementFromForeground fail');
  }
}

export default function DriverGraph() {
  const [elements, setElements] = useState<(NodeData | EdgeData)[]>([]);
  const [selectedInfo, setSelectedInfo] = useState<string | null>(null);
  const [displayedInfo, setDisplayedInfo] = useState<JSX.Element[]>([]);
  const [selectedDrivers, setSelectedDrivers] = useState<string[]>([]);
  const [minDisplayYear, setMinDisplayYear] = useState(DEFAULT_MIN_DISPLAY_YEAR);
  const [maxDisplayYear, setMaxDisplayYear] = useState(DEFAULT_MAX_DISPLAY_YEAR);
  const [minDisplayRaceCount, setMinDisplayRaceCount] = useState(DEFAULT_MIN_DISPLAY_RACE_COUNT);
  const [sliderThumbValues, setSliderThumbValues] = useState([
    DEFAULT_MIN_DISPLAY_YEAR,
    DEFAULT_MAX_DISPLAY_YEAR,
  ]); // initial slider values
  const cyRef = useRef<Core | null>(null);

  // initial graph fetch
  useEffect(() => {
    // fetch('/graph')
    //   .then((res) => res.json())
    //   .then((data) => setElements([...data.nodes, ...data.edges]))
    //   .catch((err) => console.error('Error fetching graph:', err));

    // Static presentation for demo on pages
    fetch(process.env.PUBLIC_URL + '/data/graph.json')
      .then((res) => res.json())
      .then((data) => setElements([...data.nodes, ...data.edges]))
      .catch((err) => console.error('Error fetching graph:', err));
  }, []);

  // run layout when elements are all loaded
  useEffect(() => {
    if (cyRef.current && elements.length > 0) {
      const cy = cyRef.current;

      const layout = cy.layout({
        name: 'preset',
        positions: nodePositionJSON,
      });

      layout.on('layoutstop', () => {
        cy.fit(cy.elements(':visible'), 30);
        const fitZoom = cy.zoom();
        cy.minZoom(fitZoom * 0.85);
        cy.maxZoom(fitZoom * 5);
      });

      layout.run();
      centerViewport(cy);
      cy.autolock(true);
    }
  }, [elements]);

  // handle driver selection
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().removeClass('highlighted faded');

    if (selectedDrivers.length === 1) {
      const driverId = selectedDrivers.at(0)!;
      const node = cy.getElementById(driverId);
      node.addClass('highlighted');
      // const years_active = node.data('years_active').join(', ');
      // setSelectedInfo(
      //   `Selected: ${node.data('name')}, active during ${years_active}`
      // );
      const label = node
        .data('yearsByCtor')
        .map((pair: YearsByCtor) => `${pair.ctor}[${pair.years.join(' ,')}]`)
        .join(', ');
      setSelectedInfo(`Selected: ${node.data('name')}, raced for ${label}`);
    } else if (selectedDrivers.length === 2) {
      highlightShortestPathInBrowser(selectedDrivers[0], selectedDrivers[1]);
    } else if (selectedDrivers.length === 3) {
      setSelectedDrivers([selectedDrivers.at(-1)!]);
    } else {
      // selectedDrivers === 0
      return;
    }
  }, [selectedDrivers]);

  // update visible nodes on year range change
  useEffect(() => {
    const cy = cyRef.current;
    if (cy) {
      updateNodeVisibility(cy, minDisplayRaceCount, minDisplayYear, maxDisplayYear);

      cy.edges().forEach((edge: EdgeSingular) => {
        const ctorId: string = getMostCommonCtorId(
          edge.data('yearsByCtor'),
          minDisplayYear,
          maxDisplayYear
        );

        edge.data('displayCtorId', ctorId);
      });
      centerViewport(cy);
    }
  }, [minDisplayYear, maxDisplayYear, minDisplayRaceCount, elements]);

  // TODO: What if there are multiple shortest paths of same length?
  function highlightShortestPathInBrowser(sourceId: string, targetId: string): void {
    const cy = cyRef.current;
    if (!cy) return;

    // Clear previous highlighting
    cy.elements().removeClass('highlighted faded');

    // Use built-in Dijkstra (or use .aStar() if you want heuristics)
    const dijkstra = cy.elements().dijkstra({ root: `#${sourceId}` });
    const path = dijkstra.pathTo(cy.getElementById(targetId));

    const sourceName: string = cy.getElementById(`${sourceId}`).data('name');
    const targetName: string = cy.getElementById(`${targetId}`).data('name');

    // check if path was not found
    if (path.length === 1) {
      setSelectedInfo(`No path from ${sourceName} to ${targetName}`);
      return;
    }

    // Highlight the path
    path.addClass('highlighted');

    // Fade everything else
    cy.elements().not(path).addClass('faded');

    // Show number of steps
    setSelectedInfo(
      `Shortest path from ${sourceName} to ${targetName} is ${Math.floor(path.length / 2)} steps`
    );

    const parts = [];

    for (var i = 0; i < path.length; ++i) {
      const ele = path[i];
      if (ele.isNode()) {
        parts.push(ele.data('name'));
      }
      if (ele.isEdge()) {
        // TODO: update this to be correct for the given year (maybe this is already handled with how label is set)
        parts.push('NO_TEAM');
      }
    }
    const pathString = parts.join(' -> ');
    setSelectedInfo(pathString);
  }

  // styles for nodes, edges, subclasses
  const cyStylesheet = useMemo(
    () => [
      {
        selector: 'node',
        style: {
          label: 'data(codename)',
          color: 'white',
          'text-outline-color': 'black',
          'text-outline-width': 2,
          shape: 'ellipse',
          width: DEFAULT_NODE_DIAMETER,
          height: DEFAULT_NODE_DIAMETER,
          'text-valign': 'center',
          'text-halign': 'center',
          'font-size': '14px',
          'text-margin-y': '5px',
          'text-max-width': '100px',
          'border-width': 6,
          'border-color': '#000000',
          'border-opacity': 1,

          backgroundColor: (node: NodeSingular) =>
            ctorMap[node.data('displayCtorId')].colorPrimary || '#000000',
          // Use pie to create inner ring for secondary color
          'pie-size': '100%',
          'pie-hole': '85%',
          'pie-1-background-color': (node: NodeSingular) =>
            ctorMap[node.data('displayCtorId')].colorSecondary ||
            ctorMap[node.data('displayCtorId')].colorPrimary ||
            '#000000',
          'pie-1-background-size': '100%',

          'transition-property': 'background-color, width, height',
          'transition-duration': '100ms',
        },
      },
      {
        selector: 'node.hovered',
        style: {
          width: DEFAULT_NODE_DIAMETER * NODE_HOVER_SCALE,
          height: DEFAULT_NODE_DIAMETER * NODE_HOVER_SCALE,
          'transition-property': 'width, height',
          'transition-duration': '100ms',
        },
      },
      {
        selector: 'node.neighbor-hovered',
        style: {
          width: DEFAULT_NODE_DIAMETER * 1.25,
          height: DEFAULT_NODE_DIAMETER * 1.25,
          // Use temporary hoverColor if present, otherwise fall back to displayCtorId
          backgroundColor: (node: NodeSingular) =>
            node.data('hoverColor') ??
            (ctorMap[node.data('displayCtorId')].colorPrimary || '#000000'),
          'pie-1-background-color': (node: NodeSingular) =>
            node.data('hoverColorSecondary') ??
            (ctorMap[node.data('displayCtorId')].colorSecondary ||
              ctorMap[node.data('displayCtorId')].colorPrimary ||
              '#000000'),
          'transition-property': 'background-color, width, height',
          'transition-duration': '100ms',
        },
      },
      {
        selector: 'edge',
        style: {
          width: 4,
          'line-color': '#aaaaaa',
          'font-size': 12,
          'text-rotation': 'autorotate',
          color: 'white',
          'text-outline-color': 'black',
          'text-outline-width': 2,
        },
      },
      {
        selector: 'edge.highlighted',
        style: {
          width: 16,
          label: (edge: EdgeSingular) => ctorMap[edge.data('displayCtorId')].name || '#000000',

          'transition-property': 'background-color, line-color',
          'transition-duration': '100ms',
          'z-index': 9999,
          'line-color': (edge: EdgeSingular) =>
            ctorMap[edge.data('displayCtorId')].colorPrimary || '#000000',
        },
      },
      {
        selector: '.faded',
        style: {
          opacity: 0.6,
          'text-opacity': 0.6,
        },
      },
    ],
    []
  );

  // style for cytoscape container
  const cyStyle = useMemo(
    // #f4f4f4 (Original light grey)
    // #15151e (F1.com background)
    () => ({ width: '100%', height: '100%', backgroundColor: '#272822' }),
    []
  );

  // Initialization function for cytoscape
  //  - binds event listeners
  const cyBindEventListeners = useCallback((cy: Core) => {
    cyRef.current = cy;

    if ((cy as any)._driverGraphEventsBound !== true) {
      (cy as any)._driverGraphEventsBound = true; // guard against binding duplicate listeners

      /* EVENT LISTENERS */
      cy.on('tap', 'node', (event: EventObject) => {
        const node: NodeSingular = event.target;
        const teammatesByYearByCtor: TeammatesByYearByCtor[] = node.data('teammatesByYearByCtor');

        let index: number = 0;
        const infoDivs = [
          <div
            key={index++}
            className="driverInfoDiv"
            style={{
              backgroundColor: ctorMap[node.data('displayCtorId')]?.colorPrimary || '#000000',
              borderColor: ctorMap[node.data('displayCtorId')]?.colorSecondary || '#000000',
            }}
          >
            {node.data('name')}
          </div>,
          ...teammatesByYearByCtor.map(({ ctorId, years }) => (
            <div
              key={index++}
              className="driverTeamsInfoDiv"
              style={{
                backgroundColor: ctorMap[ctorId]?.colorPrimary || '#000000',
                borderColor: ctorMap[ctorId]?.colorSecondary || '#000000',
              }}
            >
              <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>{ctorMap[ctorId].name}</div>
              {years.map(([year, teammates]) => (
                <div key={index++}>
                  {year}:{' '}
                  {teammates
                    .map((driverId) => {
                      const el = cy.getElementById(`${driverId}`);
                      return el.data('forename')[0] + '. ' + el.data('surname');
                    })
                    .join(', ')}
                </div>
              ))}
            </div>
          )),
        ];

        setDisplayedInfo(infoDivs);
      });

      cy.on('tap', 'edge', (event: EventObject) => {
        const edge: EdgeSingular = event.target;
        const yearsByCtor = edge.data('yearsByCtor');
        const driver1Name: string = edge.source().data('name') || edge.source().id();
        const driver2Name: string = edge.target().data('name') || edge.target().id();

        let index = 0;
        const infoDivs = [
          <div
            key={index++}
            className="driverInfoDiv"
            style={{
              borderColor: ctorMap[edge.data('displayCtorId')]?.colorSecondary || '#000000',
              backgroundColor: ctorMap[edge.data('displayCtorId')]?.colorPrimary || '#000000',
            }}
          >
            <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>{driver1Name}</div>
            <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>{driver2Name}</div>
          </div>,
          ...[...yearsByCtor].reverse().map((ybc: YearsByCtor) => (
            <div
              key={index++}
              className="driverTeamsInfoDiv"
              style={{
                backgroundColor: ctorMap[ybc.ctorId]?.colorPrimary || '#000000',
                borderColor: ctorMap[ybc.ctorId]?.colorSecondary || '#000000',
              }}
            >
              <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>{ybc.ctor}</div>
              <div style={{ marginTop: '0.25rem', fontSize: '0.9rem' }}>{ybc.years.join(', ')}</div>
            </div>
          )),
        ];

        setDisplayedInfo(infoDivs);
      });

      // Clear on background click
      cy.on('tap', (event: EventObject) => {
        if (event.target === cy) {
          setDisplayedInfo([]);
        }
      });

      cy.on('mouseover', 'node', (event: EventObject) => {
        const node: NodeSingular = event.target;
        node.connectedEdges().addClass('highlighted');

        addElementToForeground(node);
        node.neighborhood().forEach((edge: EdgeSingular) => {
          addElementToForeground(edge);
        });

        node.addClass('hovered');

        node.neighborhood('node').forEach((neighbor: NodeSingular) => {
          const edge: EdgeSingular = node.edgesWith(neighbor)[0];
          const edgeColor = ctorMap[edge.data('displayCtorId')]?.colorPrimary || '#000000';
          const edgeColorSecondary =
            ctorMap[edge.data('displayCtorId')]?.colorSecondary || edgeColor || '#000000';
          neighbor.data('hoverColor', edgeColor);
          neighbor.data('hoverColorSecondary', edgeColorSecondary);
          neighbor.addClass('neighbor-hovered');
        });
        cy.elements().not(node.neighborhood().union(node)).addClass('faded');

        // Highlight connected edges
        node.connectedEdges().addClass('highlighted');
      });

      cy.on('mouseout', 'node', (event: EventObject) => {
        cy.elements().removeClass('faded');
        const node: NodeSingular = event.target;
        node.connectedEdges().removeClass('highlighted');

        removeElementFromForeground(node);
        node.neighborhood().forEach((edge: any) => {
          removeElementFromForeground(edge);
        });

        node.removeClass('hovered');
        node.neighborhood('node').forEach((neighbor: NodeSingular) => {
          neighbor.removeData?.('hoverColor');
          neighbor.removeClass('neighbor-hovered');
        });

        node.connectedEdges().removeClass('highlighted');
      });

      cy.on('mouseover', 'edge', (event: EventObject) => {
        const edge: EdgeSingular = event.target;
        addElementToForeground(edge);
        edge.connectedNodes().forEach((node: NodeSingular) => {
          addElementToForeground(node);

          const edgeColor = ctorMap[edge.data('displayCtorId')]?.colorPrimary || '#000000';
          const edgeColorSecondary =
            ctorMap[edge.data('displayCtorId')]?.colorSecondary || edgeColor || '#000000';
          node.data('hoverColor', edgeColor);
          node.data('hoverColorSecondary', edgeColorSecondary);
          node.addClass('neighbor-hovered');
        });
        edge.addClass('highlighted');
      });

      cy.on('mouseout', 'edge', (event: EventObject) => {
        const edge: EdgeSingular = event.target;
        removeElementFromForeground(edge);

        edge.connectedNodes().forEach((node: NodeSingular) => {
          removeElementFromForeground(node);
          node.removeData?.('hoverColor');
          node.removeClass('neighbor-hovered');
        });
        edge.removeClass('highlighted');
      });
    }
  }, []);

  return (
    <div id="mainContainer">
      {/* Graph and Timeline Container*/}
      <div id="cyContainer">
        {/* Graph */}
        <div style={{ flex: 1 }}>
          <CytoscapeComponent
            elements={elements}
            style={cyStyle}
            stylesheet={cyStylesheet}
            cy={cyBindEventListeners}
            pixelRatio={window.devicePixelRatio || 2}
          />
        </div>

        {/* Timeline Slider */}
        <div id="timelineContainer">
          <Range
            allowOverlap={true}
            draggableTrack={true} // enabling this means can't click track to go to year
            direction={Direction.Right}
            values={sliderThumbValues}
            step={1}
            min={TIMELINE_MIN_YEAR}
            max={TIMELINE_MAX_YEAR}
            onChange={(newValues) => {
              if (newValues[0] > newValues[1]) {
                if (newValues[0] === sliderThumbValues[0]) {
                  newValues[0] = newValues[1];
                } else {
                  newValues[1] = newValues[0];
                }
              }
              setMinDisplayYear(newValues[0]);
              setMaxDisplayYear(newValues[1]);
              setSliderThumbValues(newValues);
            }}
            renderMark={({ props, index }) => (
              <div
                {...props}
                key={props.key}
                style={{
                  ...props.style,
                  width: '5px',
                  height: index % 5 === 0 ? '30px' : '20px',
                  backgroundColor:
                    sliderThumbValues[0] <= index + TIMELINE_MIN_YEAR &&
                    index + TIMELINE_MIN_YEAR <= sliderThumbValues[1]
                      ? 'black'
                      : '#ccc',
                }}
              />
            )}
            renderTrack={({ props, children }) => (
              <div
                onMouseDown={props.onMouseDown}
                onTouchStart={props.onTouchStart}
                style={{
                  ...props.style,
                  flexGrow: 1,
                  width: '90%',
                  display: 'flex',
                  height: '36px',
                }}
              >
                <div
                  ref={props.ref}
                  style={{
                    width: '100%',
                    height: '5px',
                    borderRadius: '4px',
                    background: getTrackBackground({
                      values: sliderThumbValues,
                      colors: ['#ccc', 'black', '#ccc'],
                      min: TIMELINE_MIN_YEAR,
                      max: TIMELINE_MAX_YEAR,
                    }),
                    alignSelf: 'center',
                  }}
                >
                  {children}
                </div>
              </div>
            )}
            renderThumb={({ index, props }) => (
              <div
                {...props}
                key={props.key}
                style={{
                  ...props.style,
                  height: '42px',
                  width: '5px',
                  borderRadius: '4px',
                  backgroundColor: 'black',
                  display: 'flex',
                  justifyContent: 'center',
                  alignItems: 'center',
                  boxShadow: '0px 2px 6px #AAA',
                  top: index === 0 ? '65%' : '35%',
                  pointerEvents: 'auto',
                }}
              >
                <div
                  style={{
                    position: 'absolute',
                    top: index === 0 ? '30px' : '-13px', // TODO: get rid of hardcoded vals
                    color: '#fff',
                    fontWeight: 'bold',
                    fontSize: '14px',
                    fontFamily: 'Arial,Helvetica Neue,Helvetica,sans-serif',
                    padding: '4px',
                    borderRadius: '4px',
                    backgroundColor: 'black',
                  }}
                >
                  {sliderThumbValues[index]}
                </div>
              </div>
            )}
          />
        </div>
      </div>

      {/* Display Panel*/}
      <div id="displayPanel">
        {displayedInfo.length > 0 ? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '0.5rem',
              alignItems: 'center',
            }}
          >
            {displayedInfo}
          </div>
        ) : (
          <p style={{ color: '#aaa', textAlign: 'center' }}>Click a node or edge</p>
        )}
      </div>
    </div>
  );
}
