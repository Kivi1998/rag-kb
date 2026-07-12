package com.diit.ragkb.ragcore.generation;

import com.diit.ragkb.ragcore.model.QueryEvent;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class OpenAiCompatibleAnswerGeneratorTest {

    @Test
    void parsesOpenAiSseDeltaAndStopsAtDone() throws Exception {
        String upstream = "data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n"
                + "data: {\"choices\":[{\"delta\":{\"content\":\"第一段\"}}]}\n\n"
                + "data: {\"choices\":[{\"delta\":{\"content\":\"第二段\"}}]}\n\n"
                + "data: [DONE]\n\n"
                + "data: {\"choices\":[{\"delta\":{\"content\":\"不得出现\"}}]}\n\n";
        List<QueryEvent> events = new ArrayList<>();

        OpenAiCompatibleAnswerGenerator.parseSse(new ByteArrayInputStream(upstream.getBytes(StandardCharsets.UTF_8)),
                new ObjectMapper(), events::add);

        assertEquals(List.of("第一段", "第二段"), events.stream().map(QueryEvent::content).toList());
    }
}
