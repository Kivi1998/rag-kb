package com.diit.ragkb;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * rag-kb 编排后端入口
 */
@SpringBootApplication
@EnableScheduling
public class RagKbApplication {

    public static void main(String[] args) {
        SpringApplication.run(RagKbApplication.class, args);
    }
}
