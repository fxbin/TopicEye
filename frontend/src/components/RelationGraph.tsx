'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import type { ContentRelation } from '@/types';

interface RelationGraphProps {
  contentId: number;
  contentTitle: string;
  relations: ContentRelation[];
}

interface GraphNode {
  id: number;
  title: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  isCenter: boolean;
}

interface GraphEdge {
  source: number;
  target: number;
  type: string;
  confidence: number;
}

const EDGE_COLORS: Record<string, string> = {
  same_event: '#6366f1',
  related_topic: '#14b8a6',
  temporal_cluster: '#f59e0b',
  causal: '#ef4444',
  response: '#3b82f6',
  contrast: '#a855f7',
};

const EDGE_LABELS: Record<string, string> = {
  same_event: '同事件',
  related_topic: '同话题',
  temporal_cluster: '同时段',
  causal: '因果',
  response: '回应',
  contrast: '对比',
};

const NODE_RADIUS = 20;
const CENTER_RADIUS = 28;
const REPULSION = 3000;
const ATTRACTION = 0.04;
  const DAMPING = 0.85;
const CENTER_PULL = 0.01;
const MAX_VELOCITY = 8;
const ITERATIONS = 300;

export default function RelationGraph({ contentId, contentTitle, relations }: RelationGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoveredNode, setHoveredNode] = useState<number | null>(null);
  const animRef = useRef<number | undefined>(undefined);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges] = useState<GraphEdge[]>(() =>
    relations.map((r) => ({
      source: r.source_id,
      target: r.target_id,
      type: r.relation_type,
      confidence: r.confidence,
    }))
  );
  const [dimensions, setDimensions] = useState({ width: 480, height: 320 });

  // Build nodes from content + relations
  const buildNodes = useCallback(() => {
    const allIds = new Set<number>([contentId]);
    for (const r of relations) {
      allIds.add(r.source_id);
      allIds.add(r.target_id);
    }

    const cx = dimensions.width / 2;
    const cy = dimensions.height / 2;
    return Array.from(allIds).map((id, i) => {
      const angle = (i / allIds.size) * Math.PI * 2;
      const radius = id === contentId ? 0 : 80;
      return {
        id,
        title: id === contentId ? contentTitle : relations.find((r) => r.target_id === id)?.target_title || `#${id}`,
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
        isCenter: id === contentId,
      };
    });
  }, [contentId, contentTitle, relations, dimensions]);

  // Run force simulation
  useEffect(() => {
    const initial = buildNodes();
    const localNodes = initial;
    let frame = 0;

    const tick = () => {
      if (frame >= ITERATIONS) {
        setNodes([...localNodes]);
        return;
      }
      frame++;

      const cx = dimensions.width / 2;
      const cy = dimensions.height / 2;

      // Repulsion (all pairs)
      for (let i = 0; i < localNodes.length; i++) {
        for (let j = i + 1; j < localNodes.length; j++) {
          const dx = localNodes[i].x - localNodes[j].x;
          const dy = localNodes[i].y - localNodes[j].y;
          const distSq = Math.max(dx * dx + dy * dy, 1);
          const force = REPULSION / distSq;
          const dist = Math.sqrt(distSq);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          localNodes[i].vx += fx;
          localNodes[i].vy += fy;
          localNodes[j].vx -= fx;
          localNodes[j].vy -= fy;
        }
      }

      // Attraction (edges)
      for (const edge of edges) {
        const sn = localNodes.find((n) => n.id === edge.source);
        const tn = localNodes.find((n) => n.id === edge.target);
        if (!sn || !tn) continue;
        const dx = tn.x - sn.x;
        const dy = tn.y - sn.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const force = ATTRACTION * dist * edge.confidence;
        const fx = (dx / (dist || 1)) * force;
        const fy = (dy / (dist || 1)) * force;
        sn.vx += fx;
        sn.vy += fy;
        tn.vx -= fx;
        tn.vy -= fy;
      }

      // Center pull + damping + integrate
      for (const n of localNodes) {
        n.vx += (cx - n.x) * CENTER_PULL;
        n.vy += (cy - n.y) * CENTER_PULL;
        n.vx *= DAMPING;
        n.vy *= DAMPING;
        n.vx = Math.max(-MAX_VELOCITY, Math.min(MAX_VELOCITY, n.vx));
        n.vy = Math.max(-MAX_VELOCITY, Math.min(MAX_VELOCITY, n.vy));
        n.x += n.vx;
        n.y += n.vy;
        // Keep in bounds
        const r = n.isCenter ? CENTER_RADIUS : NODE_RADIUS;
        n.x = Math.max(r + 4, Math.min(dimensions.width - r - 4, n.x));
        n.y = Math.max(r + 4, Math.min(dimensions.height - r - 4, n.y));
      }

      animRef.current = requestAnimationFrame(tick);
    };

    tick();
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [buildNodes, edges, dimensions]);

  // Final sync
  useEffect(() => {
    if (nodes.length === 0) setNodes(buildNodes());
  }, [buildNodes, nodes.length]);

  const nodeMap = new Map(nodes.map((n) => [n.id, n]));

  return (
    <div className="relative overflow-hidden rounded-lg border border-gray-200 bg-gradient-to-b from-gray-50/50 to-white" style={{ minHeight: 320 }}>
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        className="block w-full"
        viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
      >
        {/* Edges */}
        {edges.map((edge, i) => {
          const sn = nodeMap.get(edge.source);
          const tn = nodeMap.get(edge.target);
          if (!sn || !tn) return null;
          const color = EDGE_COLORS[edge.type] || '#9ca3af';
          const isHovered = hoveredNode === edge.source || hoveredNode === edge.target;
          return (
            <line
              key={`edge-${i}`}
              x1={sn.x}
              y1={sn.y}
              x2={tn.x}
              y2={tn.y}
              stroke={color}
              strokeWidth={isHovered ? 2.5 : 1.5}
              strokeOpacity={isHovered ? 0.9 : 0.5}
              strokeDasharray={edge.type === 'causal' ? '5 3' : undefined}
              markerEnd={`url(#arrow-${edge.type})`}
            />
          );
        })}

        {/* Arrow markers */}
        <defs>
          {Object.entries(EDGE_COLORS).map(([type, color]) => (
            <marker
              key={type}
              id={`arrow-${type}`}
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill={color} fillOpacity={0.6} />
            </marker>
          ))}
        </defs>

        {/* Nodes */}
        {nodes.map((node) => {
          const r = node.isCenter ? CENTER_RADIUS : NODE_RADIUS;
          const isHovered = hoveredNode === node.id;
          const fillColor = node.isCenter ? '#6366f1' : '#ffffff';
          const textColor = node.isCenter ? '#ffffff' : '#374151';
          const strokeColor = node.isCenter ? '#4f46e5' : '#d1d5db';
          return (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              className="cursor-pointer"
              onMouseEnter={() => setHoveredNode(node.id)}
              onMouseLeave={() => setHoveredNode(null)}
              onClick={() => {
                if (!node.isCenter) {
                  window.location.href = `/contents/${node.id}/reader`;
                }
              }}
            >
              <circle
                r={r}
                fill={fillColor}
                stroke={strokeColor}
                strokeWidth={isHovered ? 2.5 : 1.5}
                fillOpacity={isHovered ? 1 : 0.9}
              />
              <text
                textAnchor="middle"
                dominantBaseline="central"
                fontSize={node.isCenter ? 10 : 8}
                fontWeight={node.isCenter ? 700 : 500}
                fill={textColor}
                className="pointer-events-none select-none"
              >
                {node.title.length > 6 ? node.title.slice(0, 5) + '…' : node.title}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Hover tooltip */}
      {hoveredNode && (
        <div className="absolute bottom-2 left-2 right-2 rounded-md border border-gray-200 bg-white/95 px-3 py-1.5 text-[12px] text-gray-700 shadow-sm backdrop-blur">
          {nodes.find((n) => n.id === hoveredNode)?.title}
        </div>
      )}

      {/* Legend */}
      <div className="absolute right-2 top-2 flex flex-wrap gap-1.5 rounded-md border border-gray-100 bg-white/90 px-2 py-1.5 backdrop-blur">
        {Object.entries(EDGE_COLORS).map(([type, color]) => {
          if (!relations.some((r) => r.relation_type === type)) return null;
          return (
            <span key={type} className="flex items-center gap-1 text-[10px] text-gray-500">
              <span className="inline-block h-1.5 w-3 rounded-full" style={{ background: color }} />
              {EDGE_LABELS[type]}
            </span>
          );
        })}
      </div>
    </div>
  );
}
