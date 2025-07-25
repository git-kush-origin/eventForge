"""
Importance Calculator Module

This module calculates the overall importance score of a Slack thread by combining:
1. Activity-based metrics (from ThreadMetadata)
2. Content-based scores (from LLM analysis)
3. User context (channel membership, mentions)
4. Temporal factors (recency, frequency)

The scores are weighted and normalized to provide a final importance score
between 0 and 1, which can be used for thread prioritization.
"""

from dataclasses import dataclass
from typing import Dict, Optional
from slack.slack_client import ThreadMetadata
from llm.thread_analyzer import ThreadAnalysis

@dataclass
class ImportanceFactors:
    """Detailed breakdown of factors contributing to importance score"""
    # Activity Importance (0-1)
    activity_score: float          # Combined activity metrics
    activity_factors: Dict[str, float] = None  # Individual activity factors
    
    # Content Importance (0-1)
    content_score: float           # Combined LLM-based scores
    content_factors: Dict[str, float] = None   # Individual content factors
    
    # User Context (0-1)
    user_score: float             # Combined user context
    user_factors: Dict[str, float] = None      # Individual user factors
    
    # Temporal Importance (0-1)
    temporal_score: float         # Combined temporal factors
    temporal_factors: Dict[str, float] = None  # Individual temporal factors
    
    # Final Score (0-1)
    final_score: float           # Overall importance score

    def to_dict(self) -> Dict:
        """Convert to dictionary for easy serialization"""
        return {
            "final_score": self.final_score,
            "components": {
                "activity": {
                    "score": self.activity_score,
                    "factors": self.activity_factors
                },
                "content": {
                    "score": self.content_score,
                    "factors": self.content_factors
                },
                "user_context": {
                    "score": self.user_score,
                    "factors": self.user_factors
                },
                "temporal": {
                    "score": self.temporal_score,
                    "factors": self.temporal_factors
                }
            }
        }

class ImportanceCalculator:
    """Calculates overall thread importance by combining multiple factors"""
    
    def __init__(self):
        """Initialize with default weights"""
        # Component weights (should sum to 1)
        self.weights = {
            "activity": 0.25,     # Activity and engagement
            "content": 0.30,      # LLM-analyzed content importance
            "user": 0.25,         # User context and mentions
            "temporal": 0.20      # Time-based factors
        }
        
        # Subcomponent weights
        self.activity_weights = {
            "volume": 0.3,        # Message volume
            "participation": 0.3,  # Unique participants
            "reaction": 0.2,      # Reaction density
            "engagement": 0.2     # Message velocity and depth
        }
        
        self.content_weights = {
            "urgency": 0.3,       # Time sensitivity
            "topic": 0.3,         # Subject importance
            "question": 0.2,      # Question density
            "action": 0.2         # Work required
        }
        
        self.user_weights = {
            "direct_mention": 0.4,  # Direct @mentions
            "group_mention": 0.3,   # Group @mentions
            "channel_member": 0.3   # Channel membership
        }
        
        self.temporal_weights = {
            "recency": 0.6,        # How recent is activity
            "frequency": 0.4        # Message frequency/bursts
        }
    
    def calculate_activity_score(self, metadata: ThreadMetadata) -> Dict[str, float]:
        """Calculate activity-based importance"""
        factors = {
            "volume": metadata.activity_volume_score,
            "participation": metadata.participation_score,
            "reaction": metadata.reaction_density_score,
            "engagement": metadata.engagement_score
        }
        
        score = sum(
            self.activity_weights[factor] * value
            for factor, value in factors.items()
        )
        
        return {"score": score, "factors": factors}
    
    def calculate_content_score(self, analysis: ThreadAnalysis) -> Dict[str, float]:
        """Calculate content-based importance"""
        factors = {
            "urgency": analysis.urgency_score,
            "topic": analysis.topic_score,
            "question": analysis.question_score,
            "action": analysis.action_score
        }
        
        score = sum(
            self.content_weights[factor] * value
            for factor, value in factors.items()
        )
        
        return {"score": score, "factors": factors}
    
    def calculate_user_score(self, metadata: ThreadMetadata) -> Dict[str, float]:
        """Calculate user context importance"""
        factors = {
            "direct_mention": metadata.direct_mention_score,
            "group_mention": metadata.group_mention_score,
            "channel_member": 1.0 if metadata.is_channel_member else 0.0
        }
        
        score = sum(
            self.user_weights[factor] * value
            for factor, value in factors.items()
        )
        
        return {"score": score, "factors": factors}
    
    def calculate_temporal_score(self, metadata: ThreadMetadata) -> Dict[str, float]:
        """Calculate temporal importance"""
        factors = {
            "recency": metadata.recency_score,
            "frequency": metadata.frequency_score
        }
        
        score = sum(
            self.temporal_weights[factor] * value
            for factor, value in factors.items()
        )
        
        return {"score": score, "factors": factors}
    
    def calculate_importance(
        self,
        metadata: ThreadMetadata,
        analysis: Optional[ThreadAnalysis] = None
    ) -> ImportanceFactors:
        """
        Calculate overall thread importance
        
        Args:
            metadata: Thread metadata from Slack client
            analysis: Optional LLM analysis results
        
        Returns:
            ImportanceFactors with overall score and breakdown
        """
        # Calculate component scores
        activity = self.calculate_activity_score(metadata)
        content = self.calculate_content_score(analysis) if analysis else {"score": 0.0, "factors": {}}
        user = self.calculate_user_score(metadata)
        temporal = self.calculate_temporal_score(metadata)
        
        # Calculate final score
        final_score = sum([
            self.weights["activity"] * activity["score"],
            self.weights["content"] * content["score"],
            self.weights["user"] * user["score"],
            self.weights["temporal"] * temporal["score"]
        ])
        
        return ImportanceFactors(
            activity_score=activity["score"],
            activity_factors=activity["factors"],
            content_score=content["score"],
            content_factors=content["factors"],
            user_score=user["score"],
            user_factors=user["factors"],
            temporal_score=temporal["score"],
            temporal_factors=temporal["factors"],
            final_score=final_score
        ) 