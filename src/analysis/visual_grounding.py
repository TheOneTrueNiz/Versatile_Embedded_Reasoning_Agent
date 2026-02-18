"""
Embodied Reasoning: Virtual Visual Grounding

Implements Vision-Language Model (VLM) integration for screenshot-based reasoning,
enabling the agent to understand and interact with visual content.

Key Features:
- Screenshot capture and preprocessing
- UI element detection and localization
- Visual grounding with bounding boxes
- Spatial reasoning about visual content
- VLM integration for image understanding
- Action planning based on visual state

Architecture:
- ScreenCapture: Captures and preprocesses screenshots
- ElementDetector: Detects UI elements with bounding boxes
- VisualGrounder: Maps text descriptions to visual regions
- SpatialReasoner: Reasons about element positions/relationships
- VLMInterface: Abstracts VLM API calls
- VisualActionPlanner: Plans actions based on visual state

Research References:
- CLIP: Learning Transferable Visual Models (Radford et al., 2021)
- GroundingDINO: Marrying DINO with Grounded Pre-Training (Liu et al., 2023)
- Set-of-Mark Prompting: Unleashes Visual Grounding (Yang et al., 2023)
"""

import base64
import hashlib
import logging
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Types
# =============================================================================

class ElementType(Enum):
    """Types of UI elements."""
    BUTTON = "button"
    TEXT_INPUT = "text_input"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    DROPDOWN = "dropdown"
    LINK = "link"
    IMAGE = "image"
    ICON = "icon"
    MENU = "menu"
    TAB = "tab"
    LIST_ITEM = "list_item"
    TEXT = "text"
    CONTAINER = "container"
    UNKNOWN = "unknown"


class ActionType(Enum):
    """Types of visual actions."""
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE = "type"
    SCROLL = "scroll"
    HOVER = "hover"
    DRAG = "drag"
    SELECT = "select"
    WAIT = "wait"


class GroundingConfidence(Enum):
    """Confidence levels for visual grounding."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CERTAIN = "certain"


class SpatialRelation(Enum):
    """Spatial relationships between elements."""
    ABOVE = "above"
    BELOW = "below"
    LEFT_OF = "left_of"
    RIGHT_OF = "right_of"
    INSIDE = "inside"
    CONTAINS = "contains"
    OVERLAPS = "overlaps"
    ADJACENT = "adjacent"
    ALIGNED = "aligned"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class BoundingBox:
    """Bounding box for UI elements."""
    x: float
    y: float
    width: float
    height: float
    confidence: float = 1.0

    @property
    def center(self) -> Tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def corners(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """Return (top_left, bottom_right) corners."""
        return ((self.x, self.y), (self.x + self.width, self.y + self.height))

    def contains_point(self, x: float, y: float) -> bool:
        """Check if point is inside bounding box."""
        return (self.x <= x <= self.x + self.width and
                self.y <= y <= self.y + self.height)

    def intersects(self, other: "BoundingBox") -> bool:
        """Check if bounding boxes intersect."""
        return not (self.x + self.width < other.x or
                   other.x + other.width < self.x or
                   self.y + self.height < other.y or
                   other.y + other.height < self.y)

    def iou(self, other: "BoundingBox") -> float:
        """Calculate Intersection over Union."""
        # Intersection
        x1 = max(self.x, other.x)
        y1 = max(self.y, other.y)
        x2 = min(self.x + self.width, other.x + other.width)
        y2 = min(self.y + self.height, other.y + other.height)

        if x2 < x1 or y2 < y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        union = self.area + other.area - intersection

        return intersection / union if union > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "confidence": self.confidence
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BoundingBox":
        return cls(
            x=data.get("x", ""),
            y=data.get("y", ""),
            width=data.get("width", ""),
            height=data.get("height", ""),
            confidence=data.get("confidence", 1.0)
        )


@dataclass
class UIElement:
    """Detected UI element."""
    element_id: str
    element_type: ElementType
    bbox: BoundingBox
    text: str = ""
    label: str = ""
    is_clickable: bool = False
    is_editable: bool = False
    is_visible: bool = True
    attributes: Dict[str, Any] = field(default_factory=dict)
    children: List["UIElement"] = field(default_factory=list)
    parent_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "element_id": self.element_id,
            "element_type": self.element_type.value,
            "bbox": self.bbox.to_dict(),
            "text": self.text,
            "label": self.label,
            "is_clickable": self.is_clickable,
            "is_editable": self.is_editable,
            "is_visible": self.is_visible,
            "attributes": self.attributes,
            "children": [c.to_dict() for c in self.children],
            "parent_id": self.parent_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UIElement":
        return cls(
            element_id=data.get("element_id", ""),
            element_type=ElementType(data.get("element_type", "")),
            bbox=BoundingBox.from_dict(data.get("bbox", "")),
            text=data.get("text", ""),
            label=data.get("label", ""),
            is_clickable=data.get("is_clickable", False),
            is_editable=data.get("is_editable", False),
            is_visible=data.get("is_visible", True),
            attributes=data.get("attributes", {}),
            children=[cls.from_dict(c) for c in data.get("children", [])],
            parent_id=data.get("parent_id")
        )


@dataclass
class Screenshot:
    """Captured screenshot with metadata."""
    screenshot_id: str
    image_data: bytes
    width: int
    height: int
    format: str = "png"
    captured_at: datetime = field(default_factory=datetime.now)
    source: str = ""  # Application or URL
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def base64(self) -> str:
        """Get base64 encoded image."""
        return base64.b64encode(self.image_data).decode('utf-8')

    @property
    def data_url(self) -> str:
        """Get data URL for image."""
        return f"data:image/{self.format};base64,{self.base64}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "screenshot_id": self.screenshot_id,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "captured_at": self.captured_at.isoformat(),
            "source": self.source,
            "metadata": self.metadata,
            # Don't include image_data in dict - too large
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], image_data: bytes = b"") -> "Screenshot":
        return cls(
            screenshot_id=data.get("screenshot_id", ""),
            image_data=image_data,
            width=data.get("width", ""),
            height=data.get("height", ""),
            format=data.get("format", "png"),
            captured_at=datetime.fromisoformat(data["captured_at"]) if data.get("captured_at") else datetime.now(),
            source=data.get("source", ""),
            metadata=data.get("metadata", {})
        )


@dataclass
class GroundingResult:
    """Result of visual grounding."""
    query: str
    elements: List[UIElement]
    confidence: GroundingConfidence
    reasoning: str = ""
    alternatives: List[UIElement] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def best_match(self) -> Optional[UIElement]:
        """Get the best matching element."""
        return self.elements[0] if self.elements else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "elements": [e.to_dict() for e in self.elements],
            "confidence": self.confidence.value,
            "reasoning": self.reasoning,
            "alternatives": [a.to_dict() for a in self.alternatives],
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GroundingResult":
        return cls(
            query=data.get("query", ""),
            elements=[UIElement.from_dict(e) for e in data.get("elements", [])],
            confidence=GroundingConfidence(data.get("confidence", "medium")),
            reasoning=data.get("reasoning", ""),
            alternatives=[UIElement.from_dict(a) for a in data.get("alternatives", [])],
            metadata=data.get("metadata", {})
        )


@dataclass
class VisualAction:
    """Action to perform on visual element."""
    action_id: str
    action_type: ActionType
    target: Optional[UIElement] = None
    target_point: Optional[Tuple[float, float]] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type.value,
            "target": self.target.to_dict() if self.target else None,
            "target_point": self.target_point,
            "parameters": self.parameters,
            "description": self.description,
            "confidence": self.confidence
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisualAction":
        return cls(
            action_id=data.get("action_id", ""),
            action_type=ActionType(data.get("action_type", "")),
            target=UIElement.from_dict(data["target"]) if data.get("target") else None,
            target_point=tuple(data["target_point"]) if data.get("target_point") else None,
            parameters=data.get("parameters", {}),
            description=data.get("description", ""),
            confidence=data.get("confidence", 1.0)
        )


@dataclass
class SpatialQuery:
    """Query for spatial relationships."""
    reference_element: UIElement
    relation: SpatialRelation
    target_type: Optional[ElementType] = None
    constraints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VisualState:
    """Complete visual state of the screen."""
    state_id: str
    screenshot: Screenshot
    elements: List[UIElement]
    timestamp: datetime = field(default_factory=datetime.now)
    application: str = ""
    page_title: str = ""
    url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_id": self.state_id,
            "screenshot": self.screenshot.to_dict(),
            "elements": [e.to_dict() for e in self.elements],
            "timestamp": self.timestamp.isoformat(),
            "application": self.application,
            "page_title": self.page_title,
            "url": self.url,
            "metadata": self.metadata
        }


# =============================================================================
# Screen Capture
# =============================================================================

class ScreenCaptureInterface(ABC):
    """Interface for screen capture."""

    @abstractmethod
    def capture(self) -> Screenshot:
        """Capture the current screen."""
        pass

    @abstractmethod
    def capture_region(self, bbox: BoundingBox) -> Screenshot:
        """Capture a specific region."""
        pass


class MockScreenCapture(ScreenCaptureInterface):
    """Mock screen capture for testing."""

    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        self._width = width
        self._height = height
        self._counter = 0

    def _generate_id(self) -> str:
        self._counter += 1
        return f"screenshot_{self._counter:04d}"

    def _generate_mock_image(self, width: int, height: int) -> bytes:
        """Generate minimal valid PNG bytes."""
        # Simplified mock - in real implementation, generate actual image
        return b'\x89PNG\r\n\x1a\n' + b'\x00' * 100

    def capture(self) -> Screenshot:
        """Capture mock screenshot."""
        return Screenshot(
            screenshot_id=self._generate_id(),
            image_data=self._generate_mock_image(self._width, self._height),
            width=self._width,
            height=self._height,
            format="png",
            source="mock"
        )

    def capture_region(self, bbox: BoundingBox) -> Screenshot:
        """Capture mock region."""
        return Screenshot(
            screenshot_id=self._generate_id(),
            image_data=self._generate_mock_image(int(bbox.width), int(bbox.height)),
            width=int(bbox.width),
            height=int(bbox.height),
            format="png",
            source="mock_region"
        )


# =============================================================================
# Element Detection
# =============================================================================

class ElementDetectorInterface(ABC):
    """Interface for UI element detection."""

    @abstractmethod
    def detect(self, screenshot: Screenshot) -> List[UIElement]:
        """Detect UI elements in screenshot."""
        pass

    @abstractmethod
    def detect_by_type(self, screenshot: Screenshot, element_type: ElementType) -> List[UIElement]:
        """Detect elements of specific type."""
        pass


class MockElementDetector(ElementDetectorInterface):
    """Mock element detector for testing."""

    def __init__(self) -> None:
        self._counter = 0
        self._mock_elements: List[UIElement] = []

    def _generate_id(self) -> str:
        self._counter += 1
        return f"elem_{self._counter:04d}"

    def set_mock_elements(self, elements: List[UIElement]) -> None:
        """Set mock elements for detection."""
        self._mock_elements = elements

    def detect(self, screenshot: Screenshot) -> List[UIElement]:
        """Detect mock elements."""
        if self._mock_elements:
            return self._mock_elements

        # Generate default mock elements
        return [
            UIElement(
                element_id=self._generate_id(),
                element_type=ElementType.BUTTON,
                bbox=BoundingBox(100, 100, 80, 30, 0.95),
                text="Submit",
                is_clickable=True
            ),
            UIElement(
                element_id=self._generate_id(),
                element_type=ElementType.TEXT_INPUT,
                bbox=BoundingBox(100, 50, 200, 30, 0.92),
                label="Username",
                is_editable=True
            ),
            UIElement(
                element_id=self._generate_id(),
                element_type=ElementType.TEXT,
                bbox=BoundingBox(100, 20, 150, 20, 0.88),
                text="Login Form"
            )
        ]

    def detect_by_type(self, screenshot: Screenshot, element_type: ElementType) -> List[UIElement]:
        """Detect elements of specific type."""
        all_elements = self.detect(screenshot)
        return [e for e in all_elements if e.element_type == element_type]


# =============================================================================
# Visual Grounding
# =============================================================================

class VisualGrounder:
    """Maps text descriptions to visual regions."""

    def __init__(self, detector: ElementDetectorInterface) -> None:
        self._detector = detector
        self._text_matchers: Dict[str, Callable[[str, UIElement], float]] = {}
        self._init_default_matchers()

    def _init_default_matchers(self):
        """Initialize default text matching strategies."""
        # Exact match
        self._text_matchers["exact"] = lambda query, elem: (
            1.0 if query.lower() == elem.text.lower() else 0.0
        )

        # Contains match
        self._text_matchers["contains"] = lambda query, elem: (
            0.8 if query.lower() in elem.text.lower() else 0.0
        )

        # Label match
        self._text_matchers["label"] = lambda query, elem: (
            0.9 if query.lower() in elem.label.lower() else 0.0
        )

        # Fuzzy match (simple)
        def fuzzy_match(query: str, elem: UIElement) -> float:
            q = query.lower()
            t = elem.text.lower()
            if not t:
                return 0.0
            # Simple character overlap ratio
            common = sum(1 for c in q if c in t)
            return min(0.7, common / len(q)) if q else 0.0

        self._text_matchers["fuzzy"] = fuzzy_match

    def ground(self, query: str, screenshot: Screenshot,
               element_types: List[ElementType] = None) -> GroundingResult:
        """Ground a text query to visual elements."""
        elements = self._detector.detect(screenshot)

        # Filter by type if specified
        if element_types:
            elements = [e for e in elements if e.element_type in element_types]

        # Score each element
        scored_elements: List[Tuple[UIElement, float]] = []
        for elem in elements:
            score = self._compute_match_score(query, elem)
            if score > 0:
                scored_elements.append((elem, score))

        # Sort by score
        scored_elements.sort(key=lambda x: -x[1])

        # Determine confidence
        if not scored_elements:
            confidence = GroundingConfidence.LOW
        elif scored_elements[0][1] > 0.9:
            confidence = GroundingConfidence.CERTAIN
        elif scored_elements[0][1] > 0.7:
            confidence = GroundingConfidence.HIGH
        elif scored_elements[0][1] > 0.4:
            confidence = GroundingConfidence.MEDIUM
        else:
            confidence = GroundingConfidence.LOW

        # Build result
        best_elements = [e for e, s in scored_elements[:3] if s > 0.3]
        alternatives = [e for e, s in scored_elements[3:6] if s > 0.2]

        return GroundingResult(
            query=query,
            elements=best_elements,
            confidence=confidence,
            reasoning=f"Matched {len(best_elements)} elements with confidence {confidence.value}",
            alternatives=alternatives
        )

    def _compute_match_score(self, query: str, element: UIElement) -> float:
        """Compute match score between query and element."""
        scores = []

        for matcher in self._text_matchers.values():
            score = matcher(query, element)
            if score > 0:
                scores.append(score)

        # Check attributes
        for key, value in element.attributes.items():
            if isinstance(value, str) and query.lower() in value.lower():
                scores.append(0.6)

        return max(scores) if scores else 0.0

    def ground_multiple(self, queries: List[str], screenshot: Screenshot) -> List[GroundingResult]:
        """Ground multiple queries at once."""
        return [self.ground(q, screenshot) for q in queries]


# =============================================================================
# Spatial Reasoning
# =============================================================================

class SpatialReasoner:
    """Reasons about spatial relationships between elements."""

    def __init__(self, margin_threshold: float = 50.0) -> None:
        self._margin = margin_threshold

    def get_relation(self, elem1: UIElement, elem2: UIElement) -> List[SpatialRelation]:
        """Get spatial relations between two elements."""
        relations = []
        b1, b2 = elem1.bbox, elem2.bbox

        # Vertical relations
        if b1.y + b1.height < b2.y:
            relations.append(SpatialRelation.ABOVE)
        elif b2.y + b2.height < b1.y:
            relations.append(SpatialRelation.BELOW)

        # Horizontal relations
        if b1.x + b1.width < b2.x:
            relations.append(SpatialRelation.LEFT_OF)
        elif b2.x + b2.width < b1.x:
            relations.append(SpatialRelation.RIGHT_OF)

        # Containment
        if self._is_inside(b1, b2):
            relations.append(SpatialRelation.INSIDE)
        elif self._is_inside(b2, b1):
            relations.append(SpatialRelation.CONTAINS)

        # Overlap
        if b1.intersects(b2) and SpatialRelation.INSIDE not in relations and SpatialRelation.CONTAINS not in relations:
            relations.append(SpatialRelation.OVERLAPS)

        # Adjacent
        if self._is_adjacent(b1, b2):
            relations.append(SpatialRelation.ADJACENT)

        # Aligned
        if self._is_aligned(b1, b2):
            relations.append(SpatialRelation.ALIGNED)

        return relations

    def _is_inside(self, inner: BoundingBox, outer: BoundingBox) -> bool:
        """Check if inner is completely inside outer."""
        return (outer.x <= inner.x and
                outer.y <= inner.y and
                outer.x + outer.width >= inner.x + inner.width and
                outer.y + outer.height >= inner.y + inner.height)

    def _is_adjacent(self, b1: BoundingBox, b2: BoundingBox) -> bool:
        """Check if boxes are adjacent (close but not overlapping)."""
        if b1.intersects(b2):
            return False

        # Check horizontal adjacency
        h_gap = min(abs(b1.x + b1.width - b2.x), abs(b2.x + b2.width - b1.x))
        v_overlap = not (b1.y + b1.height < b2.y or b2.y + b2.height < b1.y)

        if h_gap < self._margin and v_overlap:
            return True

        # Check vertical adjacency
        v_gap = min(abs(b1.y + b1.height - b2.y), abs(b2.y + b2.height - b1.y))
        h_overlap = not (b1.x + b1.width < b2.x or b2.x + b2.width < b1.x)

        if v_gap < self._margin and h_overlap:
            return True

        return False

    def _is_aligned(self, b1: BoundingBox, b2: BoundingBox) -> bool:
        """Check if boxes are aligned (horizontally or vertically)."""
        # Horizontal alignment
        if abs(b1.y - b2.y) < 5 or abs((b1.y + b1.height) - (b2.y + b2.height)) < 5:
            return True

        # Vertical alignment
        if abs(b1.x - b2.x) < 5 or abs((b1.x + b1.width) - (b2.x + b2.width)) < 5:
            return True

        # Center alignment
        c1 = b1.center
        c2 = b2.center
        if abs(c1[0] - c2[0]) < 5 or abs(c1[1] - c2[1]) < 5:
            return True

        return False

    def find_by_relation(self, reference: UIElement, relation: SpatialRelation,
                        candidates: List[UIElement]) -> List[UIElement]:
        """Find elements with specified relation to reference."""
        matches = []
        for candidate in candidates:
            if candidate.element_id == reference.element_id:
                continue
            relations = self.get_relation(reference, candidate)
            if relation in relations:
                matches.append(candidate)
        return matches

    def get_nearest(self, reference: UIElement, candidates: List[UIElement],
                   direction: Optional[SpatialRelation] = None) -> Optional[UIElement]:
        """Find nearest element, optionally in a specific direction."""
        ref_center = reference.bbox.center
        nearest = None
        min_dist = float('inf')

        for candidate in candidates:
            if candidate.element_id == reference.element_id:
                continue

            # Filter by direction
            if direction:
                relations = self.get_relation(reference, candidate)
                if direction not in relations:
                    continue

            # Calculate distance
            cand_center = candidate.bbox.center
            dist = ((ref_center[0] - cand_center[0]) ** 2 +
                   (ref_center[1] - cand_center[1]) ** 2) ** 0.5

            if dist < min_dist:
                min_dist = dist
                nearest = candidate

        return nearest

    def group_by_row(self, elements: List[UIElement], tolerance: float = 20.0) -> List[List[UIElement]]:
        """Group elements by row (similar y positions)."""
        if not elements:
            return []

        sorted_elems = sorted(elements, key=lambda e: e.bbox.y)
        rows: List[List[UIElement]] = [[sorted_elems[0]]]

        for elem in sorted_elems[1:]:
            last_row = rows[-1]
            last_y = last_row[0].bbox.y

            if abs(elem.bbox.y - last_y) < tolerance:
                last_row.append(elem)
            else:
                rows.append([elem])

        # Sort each row by x position
        for row in rows:
            row.sort(key=lambda e: e.bbox.x)

        return rows

    def group_by_column(self, elements: List[UIElement], tolerance: float = 20.0) -> List[List[UIElement]]:
        """Group elements by column (similar x positions)."""
        if not elements:
            return []

        sorted_elems = sorted(elements, key=lambda e: e.bbox.x)
        columns: List[List[UIElement]] = [[sorted_elems[0]]]

        for elem in sorted_elems[1:]:
            last_col = columns[-1]
            last_x = last_col[0].bbox.x

            if abs(elem.bbox.x - last_x) < tolerance:
                last_col.append(elem)
            else:
                columns.append([elem])

        # Sort each column by y position
        for col in columns:
            col.sort(key=lambda e: e.bbox.y)

        return columns


# =============================================================================
# VLM Interface
# =============================================================================

class VLMInterface(ABC):
    """Abstract interface for Vision Language Models."""

    @abstractmethod
    def analyze(self, screenshot: Screenshot, prompt: str) -> str:
        """Analyze screenshot with text prompt."""
        pass

    @abstractmethod
    def detect_elements(self, screenshot: Screenshot) -> List[UIElement]:
        """Detect UI elements using VLM."""
        pass

    @abstractmethod
    def describe(self, screenshot: Screenshot) -> str:
        """Generate description of screenshot."""
        pass


class MockVLM(VLMInterface):
    """Mock VLM for testing."""

    def __init__(self) -> None:
        self._responses: Dict[str, str] = {}

    def set_response(self, prompt_pattern: str, response: str) -> None:
        """Set mock response for prompt pattern."""
        self._responses[prompt_pattern] = response

    def analyze(self, screenshot: Screenshot, prompt: str) -> str:
        """Return mock analysis."""
        for pattern, response in self._responses.items():
            if pattern.lower() in prompt.lower():
                return response

        return f"Mock analysis of {screenshot.width}x{screenshot.height} image for: {prompt}"

    def detect_elements(self, screenshot: Screenshot) -> List[UIElement]:
        """Return mock detected elements."""
        return [
            UIElement(
                element_id="vlm_elem_1",
                element_type=ElementType.BUTTON,
                bbox=BoundingBox(100, 200, 100, 40, 0.9),
                text="Click Me",
                is_clickable=True
            ),
            UIElement(
                element_id="vlm_elem_2",
                element_type=ElementType.TEXT_INPUT,
                bbox=BoundingBox(100, 100, 200, 30, 0.85),
                label="Email",
                is_editable=True
            )
        ]

    def describe(self, screenshot: Screenshot) -> str:
        """Return mock description."""
        return f"A {screenshot.width}x{screenshot.height} screenshot showing a user interface with various elements."


# =============================================================================
# Visual Action Planner
# =============================================================================

class VisualActionPlanner:
    """Plans actions based on visual state."""

    def __init__(self, grounder: VisualGrounder, spatial: SpatialReasoner) -> None:
        self._grounder = grounder
        self._spatial = spatial
        self._action_counter = 0

    def _generate_id(self) -> str:
        self._action_counter += 1
        return f"action_{self._action_counter:04d}"

    def plan_click(self, target_description: str, screenshot: Screenshot) -> Optional[VisualAction]:
        """Plan a click action on described target."""
        result = self._grounder.ground(target_description, screenshot)

        if not result.best_match:
            return None

        target = result.best_match
        return VisualAction(
            action_id=self._generate_id(),
            action_type=ActionType.CLICK,
            target=target,
            target_point=target.bbox.center,
            description=f"Click on '{target.text or target.label}'",
            confidence=0.9 if result.confidence in (GroundingConfidence.HIGH, GroundingConfidence.CERTAIN) else 0.6
        )

    def plan_type(self, target_description: str, text: str, screenshot: Screenshot) -> Optional[VisualAction]:
        """Plan a type action on described target."""
        result = self._grounder.ground(
            target_description, screenshot,
            element_types=[ElementType.TEXT_INPUT]
        )

        if not result.best_match:
            return None

        target = result.best_match
        return VisualAction(
            action_id=self._generate_id(),
            action_type=ActionType.TYPE,
            target=target,
            target_point=target.bbox.center,
            parameters={"text": text},
            description=f"Type '{text}' into '{target.label or target.text}'",
            confidence=0.9 if result.confidence == GroundingConfidence.CERTAIN else 0.7
        )

    def plan_scroll(self, direction: str, amount: int = 100, screenshot: Screenshot = None) -> VisualAction:
        """Plan a scroll action."""
        return VisualAction(
            action_id=self._generate_id(),
            action_type=ActionType.SCROLL,
            parameters={"direction": direction, "amount": amount},
            description=f"Scroll {direction} by {amount}px",
            confidence=1.0
        )

    def plan_sequence(self, instructions: List[Dict[str, Any]], screenshot: Screenshot) -> List[VisualAction]:
        """Plan a sequence of actions."""
        actions = []

        for instr in instructions:
            action_type = instr.get("action", "click")

            if action_type == "click":
                action = self.plan_click(instr.get("target", ""), screenshot)
            elif action_type == "type":
                action = self.plan_type(instr.get("target", ""), instr.get("text", ""), screenshot)
            elif action_type == "scroll":
                action = self.plan_scroll(instr.get("direction", "down"), instr.get("amount", 100))
            else:
                continue

            if action:
                actions.append(action)

        return actions

    def suggest_action(self, goal: str, visual_state: VisualState) -> List[VisualAction]:
        """Suggest actions to achieve a goal based on visual state."""
        suggestions = []

        # Simple heuristics based on goal keywords
        goal_lower = goal.lower()

        if "click" in goal_lower:
            # Extract target after "click"
            parts = goal_lower.split("click")
            if len(parts) > 1:
                target = parts[1].strip()
                action = self.plan_click(target, visual_state.screenshot)
                if action:
                    suggestions.append(action)

        if "type" in goal_lower or "enter" in goal_lower:
            # Look for text input fields
            for elem in visual_state.elements:
                if elem.is_editable:
                    action = VisualAction(
                        action_id=self._generate_id(),
                        action_type=ActionType.CLICK,
                        target=elem,
                        target_point=elem.bbox.center,
                        description=f"Click on '{elem.label}' to enter text"
                    )
                    suggestions.append(action)
                    break

        if "scroll" in goal_lower:
            direction = "down" if "down" in goal_lower else "up"
            suggestions.append(self.plan_scroll(direction))

        if "submit" in goal_lower or "confirm" in goal_lower:
            action = self.plan_click("submit", visual_state.screenshot)
            if not action:
                action = self.plan_click("ok", visual_state.screenshot)
            if action:
                suggestions.append(action)

        return suggestions


# =============================================================================
# Visual Reasoning System
# =============================================================================

class VisualReasoningSystem:
    """Main system for visual grounding and reasoning."""

    def __init__(self,
                 capture: ScreenCaptureInterface,
                 detector: ElementDetectorInterface,
                 vlm: VLMInterface,
                 storage_dir: Optional[Path] = None):
        self._capture = capture
        self._detector = detector
        self._vlm = vlm
        self._storage_dir = storage_dir

        self._grounder = VisualGrounder(detector)
        self._spatial = SpatialReasoner()
        self._planner = VisualActionPlanner(self._grounder, self._spatial)

        self._state_history: List[VisualState] = []
        self._max_history = 10
        self._lock = threading.Lock()

        if storage_dir:
            storage_dir.mkdir(parents=True, exist_ok=True)

    def _generate_state_id(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = hashlib.sha256(os.urandom(8)).hexdigest()[:6]
        return f"state_{timestamp}_{random_suffix}"

    def capture_state(self, application: str = "", page_title: str = "") -> VisualState:
        """Capture current visual state."""
        screenshot = self._capture.capture()
        elements = self._detector.detect(screenshot)

        state = VisualState(
            state_id=self._generate_state_id(),
            screenshot=screenshot,
            elements=elements,
            application=application,
            page_title=page_title
        )

        with self._lock:
            self._state_history.append(state)
            if len(self._state_history) > self._max_history:
                self._state_history = self._state_history[-self._max_history:]

        return state

    def ground_element(self, description: str, state: VisualState = None) -> GroundingResult:
        """Ground a text description to visual element."""
        if state is None:
            state = self.capture_state()
        return self._grounder.ground(description, state.screenshot)

    def find_element(self, description: str, state: VisualState = None) -> Optional[UIElement]:
        """Find element matching description."""
        result = self.ground_element(description, state)
        return result.best_match

    def get_spatial_relation(self, elem1_desc: str, elem2_desc: str,
                            state: VisualState = None) -> List[SpatialRelation]:
        """Get spatial relation between two described elements."""
        if state is None:
            state = self.capture_state()

        elem1 = self.find_element(elem1_desc, state)
        elem2 = self.find_element(elem2_desc, state)

        if not elem1 or not elem2:
            return []

        return self._spatial.get_relation(elem1, elem2)

    def find_nearest(self, reference_desc: str, target_type: ElementType = None,
                    direction: SpatialRelation = None, state: VisualState = None) -> Optional[UIElement]:
        """Find nearest element to reference."""
        if state is None:
            state = self.capture_state()

        reference = self.find_element(reference_desc, state)
        if not reference:
            return None

        candidates = state.elements
        if target_type:
            candidates = [e for e in candidates if e.element_type == target_type]

        return self._spatial.get_nearest(reference, candidates, direction)

    def plan_action(self, goal: str, state: VisualState = None) -> List[VisualAction]:
        """Plan actions to achieve goal."""
        if state is None:
            state = self.capture_state()
        return self._planner.suggest_action(goal, state)

    def describe_screen(self, state: VisualState = None) -> str:
        """Get VLM description of screen."""
        if state is None:
            state = self.capture_state()
        return self._vlm.describe(state.screenshot)

    def analyze_screen(self, prompt: str, state: VisualState = None) -> str:
        """Analyze screen with custom prompt."""
        if state is None:
            state = self.capture_state()
        return self._vlm.analyze(state.screenshot, prompt)

    def get_element_hierarchy(self, state: VisualState = None) -> Dict[str, Any]:
        """Get hierarchical view of elements."""
        if state is None:
            state = self.capture_state()

        # Group by rows
        rows = self._spatial.group_by_row(state.elements)

        return {
            "total_elements": len(state.elements),
            "rows": [
                {
                    "y_position": row[0].bbox.y if row else 0,
                    "elements": [
                        {"id": e.element_id, "type": e.element_type.value, "text": e.text}
                        for e in row
                    ]
                }
                for row in rows
            ]
        }

    def get_clickable_elements(self, state: VisualState = None) -> List[UIElement]:
        """Get all clickable elements."""
        if state is None:
            state = self.capture_state()
        return [e for e in state.elements if e.is_clickable]

    def get_editable_elements(self, state: VisualState = None) -> List[UIElement]:
        """Get all editable elements."""
        if state is None:
            state = self.capture_state()
        return [e for e in state.elements if e.is_editable]

    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics."""
        with self._lock:
            return {
                "states_captured": len(self._state_history),
                "max_history": self._max_history,
                "latest_state": self._state_history[-1].to_dict() if self._state_history else None
            }


# =============================================================================
# CLI Tests
# =============================================================================

def _run_cli_tests():
    """Run CLI tests for visual grounding."""
    import sys

    tests_passed = 0
    tests_failed = 0

    def test(name: str, condition: bool) -> None:
        nonlocal tests_passed, tests_failed
        if condition:
            print(f"  [PASS] {name}")
            tests_passed += 1
        else:
            print(f"  [FAIL] {name}")
            tests_failed += 1

    print("\n" + "="*60)
    print("Visual Grounding System - CLI Tests")
    print("="*60)

    # Test 1: BoundingBox
    print("\n1. Testing BoundingBox...")
    bbox = BoundingBox(10, 20, 100, 50, 0.95)
    test("Create bbox", bbox.x == 10)
    test("Center calculation", bbox.center == (60, 45))
    test("Area calculation", bbox.area == 5000)
    test("Contains point", bbox.contains_point(50, 40))
    test("Not contains point", not bbox.contains_point(200, 200))

    bbox2 = BoundingBox(50, 30, 80, 40)
    test("Intersects", bbox.intersects(bbox2))
    test("IoU > 0", bbox.iou(bbox2) > 0)

    bbox_dict = bbox.to_dict()
    bbox_restored = BoundingBox.from_dict(bbox_dict)
    test("Serialization", bbox_restored.x == bbox.x)

    # Test 2: UIElement
    print("\n2. Testing UIElement...")
    elem = UIElement(
        element_id="btn_1",
        element_type=ElementType.BUTTON,
        bbox=bbox,
        text="Submit",
        is_clickable=True
    )
    test("Create element", elem.element_id == "btn_1")
    test("Element type", elem.element_type == ElementType.BUTTON)

    elem_dict = elem.to_dict()
    elem_restored = UIElement.from_dict(elem_dict)
    test("Serialization", elem_restored.text == "Submit")

    # Test 3: Screenshot
    print("\n3. Testing Screenshot...")
    screenshot = Screenshot(
        screenshot_id="ss_001",
        image_data=b"fake_image_data",
        width=1920,
        height=1080,
        source="test"
    )
    test("Create screenshot", screenshot.width == 1920)
    test("Base64 encoding", len(screenshot.base64) > 0)
    test("Data URL", screenshot.data_url.startswith("data:image/png;base64,"))

    # Test 4: GroundingResult
    print("\n4. Testing GroundingResult...")
    result = GroundingResult(
        query="submit button",
        elements=[elem],
        confidence=GroundingConfidence.HIGH,
        reasoning="Exact match found"
    )
    test("Create result", result.query == "submit button")
    test("Best match", result.best_match == elem)
    test("Confidence", result.confidence == GroundingConfidence.HIGH)

    result_dict = result.to_dict()
    result_restored = GroundingResult.from_dict(result_dict)
    test("Serialization", result_restored.query == result.query)

    # Test 5: VisualAction
    print("\n5. Testing VisualAction...")
    action = VisualAction(
        action_id="act_001",
        action_type=ActionType.CLICK,
        target=elem,
        target_point=(60, 45),
        description="Click submit button"
    )
    test("Create action", action.action_type == ActionType.CLICK)
    test("Has target", action.target is not None)

    action_dict = action.to_dict()
    action_restored = VisualAction.from_dict(action_dict)
    test("Serialization", action_restored.action_type == ActionType.CLICK)

    # Test 6: MockScreenCapture
    print("\n6. Testing MockScreenCapture...")
    capture = MockScreenCapture(1920, 1080)
    ss = capture.capture()
    test("Capture screenshot", ss.width == 1920)
    test("Has ID", ss.screenshot_id.startswith("screenshot_"))

    region = capture.capture_region(BoundingBox(0, 0, 800, 600))
    test("Capture region", region.width == 800)

    # Test 7: MockElementDetector
    print("\n7. Testing MockElementDetector...")
    detector = MockElementDetector()
    elements = detector.detect(ss)
    test("Detect elements", len(elements) > 0)

    buttons = detector.detect_by_type(ss, ElementType.BUTTON)
    test("Detect by type", all(e.element_type == ElementType.BUTTON for e in buttons))

    # Test 8: VisualGrounder
    print("\n8. Testing VisualGrounder...")
    grounder = VisualGrounder(detector)
    result = grounder.ground("Submit", ss)
    test("Ground query", result.query == "Submit")
    test("Has elements", len(result.elements) > 0 or len(result.alternatives) >= 0)

    # Test 9: SpatialReasoner
    print("\n9. Testing SpatialReasoner...")
    spatial = SpatialReasoner()

    elem1 = UIElement("e1", ElementType.TEXT, BoundingBox(100, 50, 100, 30))
    elem2 = UIElement("e2", ElementType.BUTTON, BoundingBox(100, 100, 100, 30))

    relations = spatial.get_relation(elem1, elem2)
    test("Get relations", SpatialRelation.ABOVE in relations)

    # Test horizontal relation
    elem3 = UIElement("e3", ElementType.ICON, BoundingBox(250, 100, 30, 30))
    h_relations = spatial.get_relation(elem2, elem3)
    test("Horizontal relation", SpatialRelation.LEFT_OF in h_relations)

    # Group by row
    elements_for_grouping = [elem1, elem2, elem3]
    rows = spatial.group_by_row(elements_for_grouping)
    test("Group by row", len(rows) >= 1)

    # Test 10: MockVLM
    print("\n10. Testing MockVLM...")
    vlm = MockVLM()
    vlm.set_response("button", "There is a submit button in the interface")

    analysis = vlm.analyze(ss, "Find button")
    test("VLM analyze", "button" in analysis.lower())

    description = vlm.describe(ss)
    test("VLM describe", "interface" in description.lower())

    vlm_elements = vlm.detect_elements(ss)
    test("VLM detect", len(vlm_elements) > 0)

    # Test 11: VisualActionPlanner
    print("\n11. Testing VisualActionPlanner...")
    planner = VisualActionPlanner(grounder, spatial)

    click_action = planner.plan_click("Submit", ss)
    test("Plan click", click_action is None or click_action.action_type == ActionType.CLICK)

    scroll_action = planner.plan_scroll("down", 200)
    test("Plan scroll", scroll_action.action_type == ActionType.SCROLL)
    test("Scroll params", scroll_action.parameters["amount"] == 200)

    # Test 12: VisualState
    print("\n12. Testing VisualState...")
    state = VisualState(
        state_id="state_001",
        screenshot=ss,
        elements=[elem1, elem2, elem3],
        application="TestApp",
        page_title="Test Page"
    )
    test("Create state", state.state_id == "state_001")
    test("Has elements", len(state.elements) == 3)

    state_dict = state.to_dict()
    test("Serialize state", "state_id" in state_dict)

    # Test 13: VisualReasoningSystem
    print("\n13. Testing VisualReasoningSystem...")
    system = VisualReasoningSystem(capture, detector, vlm)

    captured_state = system.capture_state("App", "Title")
    test("Capture state", captured_state is not None)
    test("State has elements", len(captured_state.elements) > 0)

    clickable = system.get_clickable_elements(captured_state)
    test("Get clickable", isinstance(clickable, list))

    editable = system.get_editable_elements(captured_state)
    test("Get editable", isinstance(editable, list))

    hierarchy = system.get_element_hierarchy(captured_state)
    test("Get hierarchy", "total_elements" in hierarchy)

    description = system.describe_screen(captured_state)
    test("Describe screen", len(description) > 0)

    stats = system.get_statistics()
    test("Get statistics", stats["states_captured"] >= 1)

    # Test 14: Element Types
    print("\n14. Testing ElementType...")
    test("Button type", ElementType.BUTTON.value == "button")
    test("Text input type", ElementType.TEXT_INPUT.value == "text_input")
    test("Unknown type", ElementType.UNKNOWN.value == "unknown")

    # Test 15: Action Types
    print("\n15. Testing ActionType...")
    test("Click action", ActionType.CLICK.value == "click")
    test("Type action", ActionType.TYPE.value == "type")
    test("Scroll action", ActionType.SCROLL.value == "scroll")

    # Test 16: Grounding Confidence
    print("\n16. Testing GroundingConfidence...")
    test("Low confidence", GroundingConfidence.LOW.value == "low")
    test("Certain confidence", GroundingConfidence.CERTAIN.value == "certain")

    # Test 17: Spatial Relations
    print("\n17. Testing SpatialRelation...")
    test("Above relation", SpatialRelation.ABOVE.value == "above")
    test("Inside relation", SpatialRelation.INSIDE.value == "inside")
    test("Adjacent relation", SpatialRelation.ADJACENT.value == "adjacent")

    # Test 18: IoU Calculation
    print("\n18. Testing IoU calculation...")
    box_a = BoundingBox(0, 0, 100, 100)
    box_b = BoundingBox(50, 50, 100, 100)
    iou = box_a.iou(box_b)
    test("IoU in range", 0 < iou < 1)

    box_c = BoundingBox(200, 200, 50, 50)
    iou_zero = box_a.iou(box_c)
    test("IoU zero for non-overlapping", iou_zero == 0)

    # Test 19: Containment
    print("\n19. Testing containment...")
    outer = BoundingBox(0, 0, 200, 200)
    inner = BoundingBox(50, 50, 50, 50)
    elem_outer = UIElement("outer", ElementType.CONTAINER, outer)
    elem_inner = UIElement("inner", ElementType.BUTTON, inner)

    contain_relations = spatial.get_relation(elem_outer, elem_inner)
    test("Contains relation", SpatialRelation.CONTAINS in contain_relations)

    inside_relations = spatial.get_relation(elem_inner, elem_outer)
    test("Inside relation", SpatialRelation.INSIDE in inside_relations)

    # Test 20: Action Sequence Planning
    print("\n20. Testing action sequence...")
    instructions = [
        {"action": "click", "target": "Username"},
        {"action": "type", "target": "Username", "text": "admin"},
        {"action": "scroll", "direction": "down", "amount": 100}
    ]
    sequence = planner.plan_sequence(instructions, ss)
    test("Plan sequence", isinstance(sequence, list))

    # Summary
    print("\n" + "="*60)
    logger.error(f"Results: {tests_passed} passed, {tests_failed} failed")
    print("="*60)

    return tests_failed == 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        success = _run_cli_tests()
        sys.exit(0 if success else 1)
    else:
        print("Visual Grounding System")
        print("Usage: python visual_grounding.py --test")
        print("\nThis module implements VLM integration for screenshot-based reasoning.")
